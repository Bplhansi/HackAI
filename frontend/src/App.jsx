import { useEffect, useState } from "react";
import "./App.css";

const STORAGE = {
  medications: "carenest_medications",
  archive: "carenest_archive",
  snoozed: "carenest_snoozed_reminders",
  theme: "carenest_theme",
  largeText: "carenest_large_text",
  emergency: "carenest_emergency",
  name: "carenest_preferred_name",
};

// Backend address. Set VITE_API_URL in frontend/.env (or in Netlify) when deployed.
const API_URL = (
  import.meta.env.VITE_API_URL || "http://localhost:8000"
).replace(/\/$/, "");

// Small helper for calling the backend. Throws an Error with the backend's message.
async function api(path, options = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json" },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((item) => item.msg).join(" ")
      : data.detail;
    const error = new Error(detail || "Something went wrong.");
    error.status = response.status;
    throw error;
  }

  return data;
}

const WEEKDAYS = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

function localDate(date = new Date()) {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
}

function parseDate(value) {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function addDays(value, days) {
  const date = typeof value === "string" ? parseDate(value) : new Date(value);
  date.setDate(date.getDate() + days);
  return date;
}

function daysBetween(start, end) {
  const a = Date.UTC(start.getFullYear(), start.getMonth(), start.getDate());
  const b = Date.UTC(end.getFullYear(), end.getMonth(), end.getDate());
  return Math.round((b - a) / 86400000);
}

function formatDate(value) {
  const date = typeof value === "string" ? parseDate(value) : value;
  return date.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

function readJSON(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value ? JSON.parse(value) : fallback;
  } catch {
    return fallback;
  }
}

function blankForm() {
  return {
    name: "",
    quantity: "",
    dailyQuantity: "",
    collectionDate: localDate(),
    frequency: "daily",
    weekDay: 1,
    monthDay: 1,
    doses: [{ time: "09:00", quantity: "1" }],
  };
}

function normaliseMedication(medication) {
  return {
    ...medication,
    frequency: medication.frequency || "daily",
    weekDay: Number(medication.weekDay ?? 1),
    monthDay: Number(medication.monthDay ?? 1),
    doses:
      Array.isArray(medication.doses) && medication.doses.length
        ? medication.doses
        : [
            {
              time: "09:00",
              quantity: Number(medication.dailyQuantity) || 1,
            },
          ],
    collections:
      Array.isArray(medication.collections) &&
      medication.collections.length
        ? medication.collections
        : [
            {
              id: crypto.randomUUID(),
              date: medication.collectionDate,
              quantity: Number(medication.quantity),
            },
          ],
  };
}

function doseTotal(medication) {
  return (medication.doses || []).reduce(
    (total, dose) => total + Number(dose.quantity),
    0
  );
}

// What we keep in the server's "details" field: everything the server stores
// for us but doesn't calculate with (schedule, dose times, collection history).
function detailsOf(medication) {
  return {
    frequency: medication.frequency,
    weekDay: medication.weekDay,
    monthDay: medication.monthDay,
    doses: medication.doses,
    collections: medication.collections,
    needsNewCollection: Boolean(medication.needsNewCollection),
    archivedAt: medication.archivedAt || null,
  };
}

// Turn a row from GET /medications back into the shape the dashboard uses.
function fromServer(row) {
  const details = row.details || {};

  return normaliseMedication({
    ...details,
    id: row.id,
    backendId: row.id,
    name: row.name,
    quantity: details.needsNewCollection ? 0 : row.quantity_collected,
    dailyQuantity: Number(row.daily_quantity),
    collectionDate: row.collection_date,
    archived: row.archived,
    archivedAt: details.archivedAt || undefined,
  });
}

// Save one medication on the server. Returns the server's row, or throws.
async function saveToServer(medication) {
  const body = {
    quantity_collected: medication.quantity,
    collection_date: medication.collectionDate,
    daily_quantity: Number(Number(medication.dailyQuantity).toFixed(4)),
    details: detailsOf(medication),
  };

  const updateOn = async (medicationId) =>
    (
      await api("/medications/confirm-update", {
        method: "POST",
        body: { medication_id: medicationId, ...body },
      })
    ).medication;

  if (medication.backendId) return updateOn(medication.backendId);

  try {
    const result = await api("/medications/confirm-add", {
      method: "POST",
      body: { medication_name: medication.name, ...body },
    });
    return result.medication;
  } catch (error) {
    if (error.status !== 409) throw error;

    // The server already tracks this name: record a new collection on it instead.
    const { medications: list } = await api("/medications");
    const match = list.find(
      (item) =>
        !item.archived &&
        item.name.toLowerCase() === medication.name.toLowerCase()
    );
    if (!match) throw error;

    return updateOn(match.id);
  }
}

function isScheduled(medication, date) {
  const day = typeof date === "string" ? parseDate(date) : date;

  if (medication.frequency === "weekly") {
    return day.getDay() === Number(medication.weekDay);
  }

  if (medication.frequency === "monthly") {
    return day.getDate() === Number(medication.monthDay);
  }

  return true;
}

function supplyEnd(medication) {
  const quantity = Number(medication.quantity);

  if (medication.frequency === "daily") {
    const daily = Number(medication.dailyQuantity);
    return daily > 0
      ? addDays(medication.collectionDate, Math.ceil(quantity / daily))
      : null;
  }

  const total = doseTotal(medication);

  if (!(total > 0)) return null;

  let remaining = quantity;
  let cursor = addDays(medication.collectionDate, 0);

  for (let i = 0; i < 36600; i++) {
    if (isScheduled(medication, cursor)) {
      remaining -= total;

      if (remaining <= 0) {
        return addDays(cursor, 1);
      }
    }

    cursor = addDays(cursor, 1);
  }

  return null;
}

function calculateSupply(medication) {
  if (medication.needsNewCollection) {
    return {
      ...medication,
      totalDays: 0,
      remaining: null,
      endDate: null,
      percentage: 0,
    };
  }

  const endDate = supplyEnd(medication);

  if (!endDate) {
    return {
      ...medication,
      totalDays: 0,
      remaining: null,
      endDate: null,
      percentage: 0,
    };
  }

  const totalDays = Math.max(
    1,
    daysBetween(parseDate(medication.collectionDate), endDate)
  );

  const remaining = daysBetween(new Date(), endDate);

  return {
    ...medication,
    totalDays,
    remaining,
    endDate,
    percentage: Math.max(
      0,
      Math.min(100, (remaining / totalDays) * 100)
    ),
  };
}

function getStatus(remaining) {
  if (remaining === null) {
    return { text: "New collection needed", kind: "warning" };
  }

  if (remaining <= 0) {
    return { text: "Estimated supply ended", kind: "danger" };
  }

  if (remaining <= 7) {
    return { text: "Check your refill", kind: "danger" };
  }

  if (remaining <= 14) {
    return { text: "Refill approaching", kind: "warning" };
  }

  return { text: "Supply on track", kind: "success" };
}

function scheduleText(medication) {
  const doses = (medication.doses || [])
    .map((dose) => `${dose.quantity} at ${dose.time}`)
    .join(", ");

  if (medication.frequency === "weekly") {
    return `Every ${WEEKDAYS[medication.weekDay]} · ${doses}`;
  }

  if (medication.frequency === "monthly") {
    return `Monthly on day ${medication.monthDay} · ${doses}`;
  }

  return `Every day · ${doses}`;
}

function Icon({ name, size = 22 }) {
  const icons = {
    plus: <path d="M12 5v14M5 12h14" />,
    arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
    check: <path d="m4 12 5 5L20 6" />,
    close: <path d="M18 6 6 18M6 6l12 12" />,
    pill: (
      <>
        <path d="M10.5 3.5a6 6 0 0 1 8.5 8.5l-7 7a6 6 0 0 1-8.5-8.5z" />
        <path d="m8 8 8 8" />
      </>
    ),
    calendar: (
      <>
        <rect x="3" y="5" width="18" height="16" rx="2" />
        <path d="M7 3v4M17 3v4M3 10h18" />
      </>
    ),
    bell: (
      <>
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
        <path d="M10 21h4" />
      </>
    ),
    heart: (
      <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8z" />
    ),
    info: (
      <>
        <circle cx="12" cy="12" r="10" />
        <path d="M12 11v5M12 8h.01" />
      </>
    ),
    phone: (
      <path d="M22 16.9v3a2 2 0 0 1-2.2 2A19.7 19.7 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7l.5 2.8a2 2 0 0 1-.6 1.8L7.1 10a16 16 0 0 0 6.9 6.9l1.7-1.9a2 2 0 0 1 1.8-.6l2.8.5a2 2 0 0 1 1.7 2z" />
    ),
    archive: (
      <>
        <rect x="3" y="4" width="18" height="5" rx="1" />
        <path d="M5 9v11h14V9M10 13h4" />
      </>
    ),
    history: (
      <>
        <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
        <path d="M3 3v5h5M12 7v5l3 2" />
      </>
    ),
    search: (
      <>
        <circle cx="11" cy="11" r="7" />
        <path d="m16 16 5 5" />
      </>
    ),
    left: <path d="m15 18-6-6 6-6" />,
    right: <path d="m9 18 6-6-6-6" />,
  };

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {icons[name]}
    </svg>
  );
}

function MedicationCalendar({ medications, archive }) {
  const [visibleMonth, setVisibleMonth] = useState(
    () => new Date(new Date().getFullYear(), new Date().getMonth(), 1)
  );

  const [selectedDate, setSelectedDate] = useState(localDate());

  const year = visibleMonth.getFullYear();
  const month = visibleMonth.getMonth();

  const cells = [
    ...Array((new Date(year, month, 1).getDay() + 6) % 7).fill(null),
    ...Array.from(
      { length: new Date(year, month + 1, 0).getDate() },
      (_, index) => index + 1
    ),
  ];

  const events = [];

  function addEvent(date, type, title, description) {
    events.push({ date, type, title, description });
  }

  const monthStart = localDate(new Date(year, month, 1));
  const monthEnd = localDate(new Date(year, month + 1, 0));

  medications.forEach((medication) => {
    medication.collections.forEach((collection) => {
      addEvent(
        collection.date,
        "collection",
        `${medication.name} — collection recorded`,
        `${collection.quantity} tablets recorded as collected.`
      );
    });

    if (medication.needsNewCollection) return;

    const supply = calculateSupply(medication);

    if (!supply.endDate) return;

    [14, 7].forEach((days) => {
      addEvent(
        localDate(addDays(supply.endDate, -days)),
        "reminder",
        `${medication.name} — ${days}-day reminder`,
        "Check repeat prescription arrangements with your pharmacy."
      );
    });

    addEvent(
      localDate(supply.endDate),
      "end",
      `${medication.name} — estimated supply end`,
      "An estimate, not confirmation medication has run out."
    );

    const first =
      medication.collectionDate > monthStart
        ? medication.collectionDate
        : monthStart;

    const last =
      localDate(supply.endDate) < monthEnd
        ? localDate(supply.endDate)
        : monthEnd;

    for (
      let date = first;
      date < last;
      date = localDate(addDays(date, 1))
    ) {
      if (isScheduled(medication, date)) {
        medication.doses.forEach((dose) => {
          addEvent(
            date,
            "dose",
            `${dose.time} — ${medication.name}`,
            `${dose.quantity} tablet(s) scheduled (not a notification).`
          );
        });
      }
    }
  });

  archive.forEach((medication) => {
    medication.collections.forEach((collection) => {
      addEvent(
        collection.date,
        "collection",
        `${medication.name} — previous collection`,
        `${collection.quantity} tablets recorded as collected.`
      );
    });

    if (medication.archivedAt) {
      addEvent(
        medication.archivedAt,
        "archive",
        `${medication.name} — archived`,
        "Moved to Medication History."
      );
    }
  });

  const selectedEvents = events
    .filter((event) => event.date === selectedDate)
    .sort((a, b) => a.title.localeCompare(b.title));

  function changeMonth(amount) {
    const next = new Date(year, month + amount, 1);
    setVisibleMonth(next);
    setSelectedDate(localDate(next));
  }

  return (
    <div className="calendar-scene">
      <div className="calendar-caption">
        A clearer day starts here.
      </div>

      <div className="calendar-card">
        <div className="calendar-top">
          <div>
            <span className="calendar-kicker">
              YOUR MEDICATION CALENDAR
            </span>

            <h3>
              {visibleMonth.toLocaleDateString("en-GB", {
                month: "long",
                year: "numeric",
              })}
            </h3>
          </div>

          <div className="calendar-controls">
            <button
              type="button"
              onClick={() => changeMonth(-1)}
              aria-label="Previous month"
            >
              <Icon name="left" size={20} />
            </button>

            <button
              type="button"
              onClick={() => changeMonth(1)}
              aria-label="Next month"
            >
              <Icon name="right" size={20} />
            </button>
          </div>
        </div>

        <div
          className="calendar-grid"
          role="group"
          aria-label="Calendar dates"
        >
          {["M", "T", "W", "T", "F", "S", "S"].map((day, index) => (
            <span className="calendar-weekday" key={index}>
              {day}
            </span>
          ))}

          {cells.map((day, index) => {
            if (day === null) {
              return <span key={`blank-${index}`} />;
            }

            const date = localDate(new Date(year, month, day));

            const dateEvents = events.filter(
              (event) => event.date === date
            );

            const types = [
              ...new Set(dateEvents.map((event) => event.type)),
            ];

            return (
              <button
                key={date}
                type="button"
                className={[
                  "calendar-day",
                  date === localDate() ? "is-today" : "",
                  date === selectedDate ? "is-selected" : "",
                ].join(" ")}
                onClick={() => setSelectedDate(date)}
                aria-pressed={date === selectedDate}
                aria-label={`${formatDate(date)}, ${dateEvents.length} events`}
              >
                <span>{day}</span>

                <span className="calendar-dots" aria-hidden="true">
                  {types.slice(0, 3).map((type) => (
                    <i key={type} className={`dot-${type}`} />
                  ))}
                </span>
              </button>
            );
          })}
        </div>

        <div className="calendar-legend">
          {[
            ["dose", "Scheduled dose"],
            ["collection", "Collection"],
            ["reminder", "Reminder"],
            ["end", "Supply end"],
            ["archive", "Archived"],
          ].map(([type, label]) => (
            <span key={type}>
              <i className={`dot-${type}`} />
              {label}
            </span>
          ))}
        </div>

        <div className="calendar-detail" aria-live="polite">
          <strong>{formatDate(selectedDate)}</strong>

          {selectedEvents.length === 0 ? (
            <p>No recorded events on this date.</p>
          ) : (
            <ul>
              {selectedEvents.map((event, index) => (
                <li key={`${event.title}-${index}`}>
                  <span
                    className={`event-mark dot-${event.type}`}
                  />

                  <div>
                    <strong>{event.title}</strong>
                    <p>{event.description}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function App() {
  const [medications, setMedications] = useState(() => {
    const saved = readJSON(STORAGE.medications, []);
    return Array.isArray(saved)
      ? saved.map(normaliseMedication)
      : [];
  });

  const [archive, setArchive] = useState(() => {
    const saved = readJSON(STORAGE.archive, []);
    return Array.isArray(saved)
      ? saved.map(normaliseMedication)
      : [];
  });

  const [snoozed, setSnoozed] = useState(() =>
    readJSON(STORAGE.snoozed, {})
  );

  const [theme, setTheme] = useState(
    () => localStorage.getItem(STORAGE.theme) || "warm"
  );

  const [largeText, setLargeText] = useState(() =>
    readJSON(STORAGE.largeText, false)
  );

  const [preferredName, setPreferredName] = useState(
    () => localStorage.getItem(STORAGE.name) || ""
  );

  const [emergency, setEmergency] = useState(() =>
    readJSON(STORAGE.emergency, {
      patientName: "",
      allergies: "",
      medicalNotes: "",
      contactName: "",
      contactPhone: "",
      secondContactName: "",
      secondContactPhone: "",
    })
  );

  const [editingName, setEditingName] = useState(false);
  const [showEmergency, setShowEmergency] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState(null);

  const [form, setForm] = useState(blankForm);

  const [formError, setFormError] = useState("");
  const [toast, setToast] = useState("");

  const [historySearch, setHistorySearch] = useState("");
  const [expandedHistory, setExpandedHistory] = useState(null);

  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);

  // "loading", "online" (data comes from the server) or "offline" (this device only)
  const [serverStatus, setServerStatus] = useState("loading");
  const [saving, setSaving] = useState(false);

  const [messages, setMessages] = useState([
    {
      role: "assistant",
      text:
        'Hello! Tell me what you collected, for example "I picked up 60 tablets of ExampleMed today, one a day", and I\'ll fill in the form for you to check.',
    },
  ]);

  useEffect(() => {
    localStorage.setItem(
      STORAGE.medications,
      JSON.stringify(medications)
    );
  }, [medications]);

  useEffect(() => {
    localStorage.setItem(STORAGE.archive, JSON.stringify(archive));
  }, [archive]);

  useEffect(() => {
    localStorage.setItem(STORAGE.snoozed, JSON.stringify(snoozed));
  }, [snoozed]);

  useEffect(() => {
    localStorage.setItem(STORAGE.theme, theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem(
      STORAGE.largeText,
      JSON.stringify(largeText)
    );
  }, [largeText]);

  useEffect(() => {
    localStorage.setItem(STORAGE.name, preferredName);
  }, [preferredName]);

  useEffect(() => {
    localStorage.setItem(
      STORAGE.emergency,
      JSON.stringify(emergency)
    );
  }, [emergency]);

  // The server's database is the main copy. localStorage is only a cache for when
  // the server can't be reached, so the page still works offline.
  useEffect(() => {
    let cancelled = false;

    async function loadFromServer() {
      try {
        const { medications: rows } = await api("/medications");

        // One-time move: medications saved only in this browser before the
        // server existed are uploaded, so they show up on every device.
        const localOnly = readJSON(STORAGE.medications, [])
          .map(normaliseMedication)
          .filter((item) => !item.backendId && !item.needsNewCollection);
        const kept = [];

        for (const medication of localOnly) {
          try {
            rows.push(await saveToServer(medication));
          } catch {
            kept.push(medication);
          }
        }

        if (cancelled) return;

        const all = rows.map(fromServer);
        setMedications([...all.filter((item) => !item.archived), ...kept]);
        setArchive(all.filter((item) => item.archived));
        setServerStatus("online");
      } catch {
        if (!cancelled) setServerStatus("offline");
      }
    }

    loadFromServer();
    return () => {
      cancelled = true;
    };
    // Runs once when the page opens.
  }, []);

  useEffect(() => {
    if (!toast) return;

    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  const active = medications.map(calculateSupply);

  const attentionCount = active.filter(
    (medication) =>
      medication.needsNewCollection ||
      (medication.remaining !== null &&
        medication.remaining <= 14)
  ).length;

  const reminders = active.filter(
    (medication) =>
      !medication.needsNewCollection &&
      medication.remaining !== null &&
      medication.remaining <= 14 &&
      (!snoozed[medication.id] ||
        snoozed[medication.id] <= localDate())
  );

  const filteredArchive = archive.filter((medication) =>
    medication.name
      .toLowerCase()
      .includes(historySearch.toLowerCase())
  );

  const hour = new Date().getHours();

  const greeting =
    hour < 12
      ? "Good morning"
      : hour < 17
        ? "Good afternoon"
        : "Good evening";

  function scrollToForm() {
    setTimeout(() => {
      document.getElementById("medication-form")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }, 50);
  }

  function openAddForm() {
    setEditingId(null);
    setForm(blankForm());
    setFormError("");
    setShowForm(true);
    scrollToForm();
  }

  function openCollectionForm(medication) {
    setEditingId(medication.id);

    setForm({
      ...blankForm(),
      name: medication.name,
      dailyQuantity: String(medication.dailyQuantity),
      frequency: medication.frequency,
      weekDay: medication.weekDay,
      monthDay: medication.monthDay,
      doses: medication.doses.map((dose) => ({
        ...dose,
        quantity: String(dose.quantity),
      })),
    });

    setFormError("");
    setShowForm(true);
    scrollToForm();
  }

  async function saveMedication(event) {
    event.preventDefault();

    const name = form.name.trim();
    const quantity = Number(form.quantity);
    const totalPerScheduledDay = doseTotal(form);

    const dailyQuantity =
      form.frequency === "daily"
        ? totalPerScheduledDay
        : form.frequency === "weekly"
          ? totalPerScheduledDay / 7
          : totalPerScheduledDay / 30;

    const date = parseDate(form.collectionDate);

    if (!name) {
      setFormError("Please enter the medication name.");
      return;
    }

    if (!Number.isInteger(quantity) || quantity <= 0) {
      setFormError(
        "Please enter a whole number of tablets greater than zero."
      );
      return;
    }

    if (
      !form.doses.length ||
      form.doses.some(
        (dose) =>
          !/^([01]\d|2[0-3]):[0-5]\d$/.test(dose.time) ||
          !Number.isFinite(Number(dose.quantity)) ||
          Number(dose.quantity) <= 0
      )
    ) {
      setFormError(
        "Enter a valid time and quantity greater than zero for every dose."
      );
      return;
    }

    if (
      form.frequency === "monthly" &&
      (!Number.isInteger(Number(form.monthDay)) ||
        Number(form.monthDay) < 1 ||
        Number(form.monthDay) > 28)
    ) {
      setFormError(
        "Choose a day between 1 and 28 so the schedule works every month."
      );
      return;
    }

    if (
      !form.collectionDate ||
      Number.isNaN(date.getTime()) ||
      localDate(date) !== form.collectionDate ||
      form.collectionDate > localDate()
    ) {
      setFormError("Please enter a valid collection date.");
      return;
    }

    const current = medications.find((item) => item.id === editingId);

    const collection = {
      id: crypto.randomUUID(),
      date: form.collectionDate,
      quantity,
    };

    const schedule = {
      frequency: form.frequency,
      weekDay: Number(form.weekDay),
      monthDay: Number(form.monthDay),
      doses: form.doses.map((dose) => ({
        time: dose.time,
        quantity: Number(dose.quantity),
      })),
    };

    const next = {
      ...current,
      ...schedule,
      id: current ? current.id : crypto.randomUUID(),
      name: current ? current.name : name,
      quantity,
      dailyQuantity,
      collectionDate: form.collectionDate,
      collections: [...(current?.collections || []), collection],
      needsNewCollection: false,
    };

    // The user has checked the form and pressed Save, so now the server saves it.
    let saved = next;
    let offline = false;

    setSaving(true);
    try {
      saved = fromServer(await saveToServer(next));
    } catch (error) {
      if (error.status) {
        // The server refused it (for example an invalid date): nothing was saved.
        setFormError(error.message);
        setSaving(false);
        return;
      }
      offline = true; // no connection: keep it on this device for now
    }
    setSaving(false);

    setMedications((old) =>
      current
        ? old.map((item) => (item.id === current.id ? saved : item))
        : [...old, saved]
    );

    if (current) {
      setSnoozed((old) => {
        const copy = { ...old };
        delete copy[current.id];
        return copy;
      });
    }

    setToast(
      offline
        ? "Saved on this device only. Could not reach the medAssist AI server."
        : current
          ? "New collection recorded. Calendar updated."
          : "Medication saved. Calendar updated."
    );

    setShowForm(false);
    setEditingId(null);
  }

  // Move a medication to or from Medication History on the server.
  // Returns false if the server refused, so the screen isn't changed.
  async function setArchivedOnServer(medication, archived) {
    if (!medication.backendId) return true;

    try {
      await api(`/medications/${medication.backendId}/archive`, {
        method: "POST",
        body: { archived, details: detailsOf(medication) },
      });
      return true;
    } catch (error) {
      if (error.status) {
        setToast(error.message);
        return false;
      }
      return true; // offline: change it on this device for now
    }
  }

  // Fill the form from the assistant's suggestion. Nothing is saved until the user presses Save.
  function openFormFromAI(result) {
    const p = result.parameters;

    // Match by server id, or by name for medications the server doesn't know yet.
    const medication = medications.find((item) =>
      result.action === "update_medication_supply"
        ? item.backendId === p.medication_id
        : item.name.toLowerCase() === p.medication_name.toLowerCase()
    );

    if (result.action === "update_medication_supply" || medication) {
      if (!medication) return false;

      openCollectionForm(medication);
      setForm((old) => ({
        ...old,
        quantity: String(p.quantity_collected),
        collectionDate: p.collection_date,
      }));
      return true;
    }

    setEditingId(null);
    setForm({
      ...blankForm(),
      name: p.medication_name,
      quantity: String(p.quantity_collected),
      collectionDate: p.collection_date,
      dailyQuantity: String(p.daily_quantity),
      doses: [{ time: "09:00", quantity: String(p.daily_quantity) }],
    });
    setFormError("");
    setShowForm(true);
    scrollToForm();
    return true;
  }

  async function archiveMedication(medication) {
    const confirmed = window.confirm(
      `Move "${medication.name}" to Medication History?\n\n` +
        "It will disappear from active medications and stop showing refill reminders. You can restore it later."
    );

    if (!confirmed) return;

    const archived = {
      ...medication,
      archived: true,
      archivedAt: localDate(),
    };

    if (!(await setArchivedOnServer(archived, true))) return;

    setArchive((old) => [archived, ...old]);

    setMedications((old) =>
      old.filter((item) => item.id !== medication.id)
    );

    setSnoozed((old) => {
      const next = { ...old };
      delete next[medication.id];
      return next;
    });

    setToast("Medication moved to History.");
  }

  async function restoreMedication(medication) {
    const confirmed = window.confirm(
      `Restore "${medication.name}" to active medications?\n\n` +
        "You'll need to record a new collection before supply reminders restart."
    );

    if (!confirmed) return;

    const restored = {
      ...medication,
      quantity: 0,
      collectionDate: localDate(),
      needsNewCollection: true,
      archived: false,
      archivedAt: undefined,
    };

    if (!(await setArchivedOnServer(restored, false))) return;

    setArchive((old) =>
      old.filter((item) => item.id !== medication.id)
    );

    setMedications((old) => [...old, restored]);

    setToast("Medication restored. Record a new collection.");

    setTimeout(() => {
      document.getElementById("medications")?.scrollIntoView({
        behavior: "smooth",
      });
    }, 50);
  }

  function snoozeReminder(id) {
    setSnoozed((old) => ({
      ...old,
      [id]: localDate(addDays(localDate(), 1)),
    }));

    setToast("Reminder hidden until tomorrow.");
  }

  // Offline help, used only when the medAssist AI server can't be reached.
  function helpReply(text) {
    const input = text.toLowerCase();

    let reply =
      "I can help you find things on medAssist AI. Use the menu at the top to explore your medications, calendar, history and emergency details.";

    if (/archive|history|past|old medication/.test(input)) {
      reply =
        "Open Medication History to see previously tracked medications. You can view collection records or restore a medication.";
    } else if (/calendar|date|month/.test(input)) {
      reply =
        "The calendar shows scheduled dose times, collection dates, refill reminders and estimated supply dates. Select any date to see details.";
    } else if (/weekly|monday|daily|schedule|time|dose/.test(input)) {
      reply =
        "When adding medication, choose Daily, Weekly or Monthly. Select a day if needed, then add one or more prescribed dose times. These are calendar entries, not alarms.";
    } else if (/collect|tablet|add|medication/.test(input)) {
      reply =
        "Select Add medication, enter the collection details and prescribed schedule, then save. For an existing medication, select I've collected more.";
    } else if (/remind|refill|run out|supply/.test(input)) {
      reply =
        "medAssist AI estimates supply dates and shows in-app refill reminders when 14 days or fewer remain. Check arrangements with your pharmacy.";
    } else if (/emergency|allerg|contact/.test(input)) {
      reply =
        "Open Emergency details to enter contacts and self-reported information. In a UK emergency, call 999.";
    } else if (/theme|dark|contrast|font|text/.test(input)) {
      reply =
        "Use Display at the top to choose Warm, Dark or High Contrast. Select Larger text if you'd like bigger writing.";
    }

    return reply;
  }

  async function sendMessage(event) {
    event.preventDefault();

    const text = chatInput.trim();
    if (!text || chatLoading) return;

    // The last few turns, so the AI understands follow-ups like "it's ExampleMed".
    const conversation_context = messages.slice(-6).map((message) => ({
      role: message.role,
      content: message.text,
    }));

    setMessages((old) => [...old, { role: "user", text }]);
    setChatInput("");
    setChatLoading(true);

    let reply;

    try {
      // NVIDIA Nemotron (via Nebius Token Factory) reads the message on the backend.
      const result = await api("/chat", {
        method: "POST",
        body: { message: text, conversation_context },
      });

      reply = result.message;

      if (result.requires_confirmation && openFormFromAI(result)) {
        reply += " I've filled in the form below. Check it, then press Save.";
      }
    } catch (error) {
      reply =
        error.status === 503
          ? "The assistant is unavailable right now. You can still add your medication with the form."
          : `I couldn't reach the medAssist AI server. ${helpReply(text)}`;
    }

    setMessages((old) => [...old, { role: "assistant", text: reply }]);
    setChatLoading(false);
  }

  function telephone(value) {
    return `tel:${value.replace(/[^\d+]/g, "")}`;
  }

  return (
    <div
      className={`app theme-${theme} ${
        largeText ? "large-text" : ""
      }`}
    >
      {/* NAVIGATION */}

      <header className="site-header">
        <div className="navigation">
          <a href="#home" className="logo">
            <span className="logo-symbol">
              <Icon name="heart" size={21} />
            </span>
            medAssist AI
            <span className="logo-period">.</span>
          </a>

          <nav className="nav-links" aria-label="Main navigation">
            <a href="#medications">Medications</a>
            <a href="#calendar">Calendar</a>
            <a href="#history">History</a>
            <a href="#emergency">Emergency</a>
            <a href="#guide">Help</a>
          </nav>

          <div className="accessibility">
            <label className="display-control">
              <span>Display</span>
              <select
                value={theme}
                onChange={(event) => setTheme(event.target.value)}
                aria-label="Display theme"
              >
                <option value="warm">Warm</option>
                <option value="dark">Dark</option>
                <option value="contrast">High contrast</option>
              </select>
            </label>

            <button
              type="button"
              className="text-button"
              aria-pressed={largeText}
              onClick={() => setLargeText((old) => !old)}
            >
              {largeText ? "A− Normal text" : "A+ Larger text"}
            </button>
          </div>
        </div>
      </header>

      <main id="home">
        {serverStatus === "offline" && (
          <p className="server-banner" role="status">
            Can't reach the medAssist AI server, so you're seeing what's saved on
            this device. Changes will only be kept here for now.
          </p>
        )}
        {/* HERO */}

        <section className="hero wrap">
          <div className="hero-copy">
            <p className="overline">
              SIMPLE MEDICATION SUPPORT, EVERY DAY
            </p>

            <h1>
              Your medication,
              <br />
              <em>made simpler.</em>
            </h1>

            <p className="hero-description">
              An easier way to stay organised, feel prepared and know
              when it's time to check your next prescription.
            </p>

            <div className="hero-buttons">
              <button
                type="button"
                className="button button-primary"
                onClick={openAddForm}
              >
                Add medication
                <Icon name="arrow" size={19} />
              </button>

              <a href="#guide" className="text-link">
                See how it works
                <Icon name="arrow" size={18} />
              </a>
            </div>

            <p className="hero-small">
              <Icon name="heart" size={18} />
              Designed for clarity, comfort and independence.
            </p>
          </div>

          <div id="calendar">
            <MedicationCalendar
              medications={medications}
              archive={archive}
            />
          </div>
        </section>

        {/* PERSONAL GREETING */}

        <section className="welcome-strip wrap">
          <div>
            <span className="small-label">YOUR SPACE</span>

            <h2>
              {greeting}
              {preferredName.trim()
                ? `, ${preferredName.trim()}`
                : ""}
              .
            </h2>

            <p>
              {medications.length === 0
                ? "Start by adding your first medication."
                : attentionCount > 0
                  ? `${attentionCount} medication${
                      attentionCount === 1 ? "" : "s"
                    } may need your attention.`
                  : "Your recorded medication supply looks on track."}
            </p>
          </div>

          {editingName ? (
            <form
              className="name-form"
              onSubmit={(event) => {
                event.preventDefault();
                setEditingName(false);
                setToast("Preferred name saved.");
              }}
            >
              <label htmlFor="preferred-name">Preferred name</label>

              <div className="name-input-row">
                <input
                  id="preferred-name"
                  value={preferredName}
                  maxLength="40"
                  onChange={(event) =>
                    setPreferredName(event.target.value)
                  }
                  placeholder="Your first name"
                />

                <button
                  className="button button-primary"
                  type="submit"
                >
                  Save
                </button>
              </div>
            </form>
          ) : (
            <button
              type="button"
              className="button button-outline"
              onClick={() => setEditingName(true)}
            >
              {preferredName
                ? "Change my name"
                : "Personalise greeting"}
            </button>
          )}
        </section>

        {/* HOW TO USE */}

        <section className="intro-section wrap" id="guide">
          <div className="intro-heading">
            <div>
              <p className="overline">GETTING STARTED</p>
              <h2>Care that feels uncomplicated.</h2>
            </div>

            <p>
              Designed with older adults in mind. Clear instructions,
              readable text and three simple steps.
            </p>
          </div>

          <div className="steps">
            <article className="step">
              <span className="step-number">01</span>
              <h3>Add your medication</h3>
              <p>
                Record what you've collected and your prescribed
                daily, weekly or monthly schedule.
              </p>
            </article>

            <article className="step">
              <span className="step-number">02</span>
              <h3>Check your calendar</h3>
              <p>
                See scheduled dose times, collection dates, refill
                reminders and estimated supply dates.
              </p>
            </article>

            <article className="step">
              <span className="step-number">03</span>
              <h3>Keep your history</h3>
              <p>
                Archive old medications and find their records
                whenever needed.
              </p>
            </article>
          </div>
        </section>

        {/* OVERVIEW */}

        <section className="dashboard-section wrap">
          <div className="section-intro">
            <div>
              <p className="overline">YOUR OVERVIEW</p>
              <h2>Everything in one place.</h2>
            </div>

            <span className="date-label">
              <Icon name="calendar" size={18} />
              {formatDate(new Date())}
            </span>
          </div>

          <div className="overview-grid">
            <div className="overview-item">
              <span className="overview-icon">
                <Icon name="pill" />
              </span>
              <strong>{medications.length}</strong>
              <span>Active medications</span>
            </div>

            <div className="overview-item">
              <span className="overview-icon">
                <Icon name="bell" />
              </span>
              <strong>{attentionCount}</strong>
              <span>May need attention</span>
            </div>

            <div className="overview-item">
              <span className="overview-icon">
                <Icon name="archive" />
              </span>
              <strong>{archive.length}</strong>
              <span>In medication history</span>
            </div>
          </div>
        </section>

        {/* ADD MEDICATION FORM */}

        {showForm && (
          <section
            className="content-section wrap form-section"
            id="medication-form"
          >
            <div className="section-top">
              <div>
                <p className="overline">MEDICATION DETAILS</p>

                <h2>
                  {editingId
                    ? "Record a new collection"
                    : "Add medication"}
                </h2>

                <p className="section-subtitle">
                  Enter the details from your medication packaging
                  and prescribed schedule.
                </p>
              </div>

              <button
                type="button"
                className="close-button"
                onClick={() => setShowForm(false)}
                aria-label="Close form"
              >
                <Icon name="close" />
              </button>
            </div>

            <form onSubmit={saveMedication}>
              <div className="form-grid">
                <div className="field">
                  <label htmlFor="med-name">Medication name</label>

                  <input
                    id="med-name"
                    value={form.name}
                    readOnly={Boolean(editingId)}
                    onChange={(event) =>
                      setForm({
                        ...form,
                        name: event.target.value,
                      })
                    }
                    placeholder="e.g. ExampleMed"
                    required
                  />
                </div>

                <div className="field">
                  <label htmlFor="med-quantity">
                    Tablets collected
                  </label>

                  <input
                    id="med-quantity"
                    type="number"
                    min="1"
                    step="1"
                    value={form.quantity}
                    onChange={(event) =>
                      setForm({
                        ...form,
                        quantity: event.target.value,
                      })
                    }
                    placeholder="e.g. 60"
                    required
                  />
                </div>

                <div className="field">
                  <label htmlFor="med-date">Date collected</label>

                  <input
                    id="med-date"
                    type="date"
                    max={localDate()}
                    value={form.collectionDate}
                    onChange={(event) =>
                      setForm({
                        ...form,
                        collectionDate: event.target.value,
                      })
                    }
                    required
                  />
                </div>

                <div className="field">
                  <label htmlFor="med-frequency">
                    How often is it prescribed?
                  </label>

                  <select
                    id="med-frequency"
                    value={form.frequency}
                    onChange={(event) =>
                      setForm({
                        ...form,
                        frequency: event.target.value,
                      })
                    }
                  >
                    <option value="daily">Every day</option>
                    <option value="weekly">
                      Once a week (one chosen day)
                    </option>
                    <option value="monthly">
                      Once a month (one chosen date)
                    </option>
                  </select>
                </div>

                {form.frequency === "weekly" && (
                  <div className="field">
                    <label htmlFor="med-weekday">
                      Day of the week
                    </label>

                    <select
                      id="med-weekday"
                      value={form.weekDay}
                      onChange={(event) =>
                        setForm({
                          ...form,
                          weekDay: Number(event.target.value),
                        })
                      }
                    >
                      {WEEKDAYS.map((day, index) => (
                        <option key={day} value={index}>
                          {day}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {form.frequency === "monthly" && (
                  <div className="field">
                    <label htmlFor="med-monthday">
                      Day of each month
                    </label>

                    <select
                      id="med-monthday"
                      value={form.monthDay}
                      onChange={(event) =>
                        setForm({
                          ...form,
                          monthDay: Number(event.target.value),
                        })
                      }
                    >
                      {Array.from({ length: 28 }, (_, index) => (
                        <option
                          key={index + 1}
                          value={index + 1}
                        >
                          {index + 1}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>

              <div className="dose-editor">
                <h3>Prescribed dose times</h3>

                <p className="help-note">
                  Add each time and how many tablets are taken at
                  that time. For weekly or monthly medication, these
                  times apply only on the selected day.
                </p>

                <div className="schedule-dose-list">
                  {form.doses.map((dose, index) => (
                    <div
                      className="schedule-dose-row"
                      key={index}
                    >
                      <div className="field">
                        <label htmlFor={`dose-time-${index}`}>
                          Time {index + 1}
                        </label>

                        <input
                          id={`dose-time-${index}`}
                          type="time"
                          value={dose.time}
                          onChange={(event) =>
                            setForm((old) => ({
                              ...old,
                              doses: old.doses.map((item, itemIndex) =>
                                itemIndex === index
                                  ? {
                                      ...item,
                                      time: event.target.value,
                                    }
                                  : item
                              ),
                            }))
                          }
                          required
                        />
                      </div>

                      <div className="field">
                        <label htmlFor={`dose-qty-${index}`}>
                          Tablets at this time
                        </label>

                        <input
                          id={`dose-qty-${index}`}
                          type="number"
                          min="0.5"
                          step="0.5"
                          value={dose.quantity}
                          onChange={(event) =>
                            setForm((old) => ({
                              ...old,
                              doses: old.doses.map((item, itemIndex) =>
                                itemIndex === index
                                  ? {
                                      ...item,
                                      quantity: event.target.value,
                                    }
                                  : item
                              ),
                            }))
                          }
                          required
                        />
                      </div>

                      {form.doses.length > 1 && (
                        <button
                          className="button button-outline"
                          type="button"
                          onClick={() =>
                            setForm((old) => ({
                              ...old,
                              doses: old.doses.filter(
                                (_, itemIndex) => itemIndex !== index
                              ),
                            }))
                          }
                        >
                          Remove
                        </button>
                      )}
                    </div>
                  ))}
                </div>

                <div className="action-row">
                  <button
                    className="button button-outline"
                    type="button"
                    onClick={() =>
                      setForm((old) => ({
                        ...old,
                        doses: [
                          ...old.doses,
                          { time: "14:00", quantity: "1" },
                        ],
                      }))
                    }
                  >
                    <Icon name="plus" size={18} />
                    Add another time
                  </button>
                </div>
              </div>

              <p className="help-note">
                Estimated supply assumes each scheduled dose is
                taken. Times appear in the calendar only; medAssist AI
                does not send alarms or notifications. Always follow
                your prescription or pharmacist.
              </p>

              {formError && (
                <p className="error-message" role="alert">
                  {formError}
                </p>
              )}

              <div className="action-row">
                <button
                  type="submit"
                  className="button button-primary"
                  disabled={saving}
                >
                  <Icon name="check" size={19} />

                  {editingId
                    ? "Save new collection"
                    : "Save medication"}
                </button>

                <button
                  type="button"
                  className="button button-outline"
                  onClick={() => setShowForm(false)}
                >
                  Cancel
                </button>
              </div>
            </form>
          </section>
        )}

        {/* ACTIVE MEDICATIONS */}

        <section
          className="content-section wrap"
          id="medications"
        >
          <div className="section-top">
            <div>
              <p className="overline">
                MEDICATION MANAGEMENT
              </p>

              <h2>My medications</h2>

              <p className="section-subtitle">
                Your current medications, prescribed schedules
                and estimated supply.
              </p>
            </div>

            <button
              type="button"
              className="button button-primary"
              onClick={openAddForm}
            >
              <Icon name="plus" size={19} />
              Add new
            </button>
          </div>

          {active.length === 0 ? (
            <div className="empty-state">
              <span className="empty-icon">
                <Icon name="pill" size={32} />
              </span>

              <h3>Let's get you started.</h3>

              <p>
                Your medications will appear here once you've
                added them.
              </p>

              <button
                type="button"
                className="button button-primary"
                onClick={openAddForm}
              >
                Add your first medication
              </button>
            </div>
          ) : (
            <div className="medication-list">
              {active.map((medication) => {
                if (medication.needsNewCollection) {
                  return (
                    <article
                      className="medication-row"
                      key={medication.id}
                    >
                      <div className="medication-main">
                        <span className="medication-symbol">
                          <Icon name="pill" size={26} />
                        </span>

                        <div>
                          <h3>{medication.name}</h3>
                          <p>
                            Restored from history ·{" "}
                            {scheduleText(medication)}
                          </p>
                        </div>

                        <span className="status status-warning">
                          New collection needed
                        </span>
                      </div>

                      <p className="help-note">
                        Record your latest collection to restart
                        supply estimates.
                      </p>

                      <button
                        type="button"
                        className="button button-primary"
                        onClick={() =>
                          openCollectionForm(medication)
                        }
                      >
                        Record new collection
                      </button>
                    </article>
                  );
                }

                const status = getStatus(medication.remaining);

                return (
                  <article
                    className="medication-row"
                    key={medication.id}
                  >
                    <div className="medication-main">
                      <span className="medication-symbol">
                        <Icon name="pill" size={26} />
                      </span>

                      <div>
                        <h3>{medication.name}</h3>

                        <p>
                          {medication.quantity} tablets collected
                        </p>

                        <p className="schedule-description">
                          {scheduleText(medication)}
                        </p>
                      </div>

                      <span
                        className={`status status-${status.kind}`}
                      >
                        {status.text}
                      </span>
                    </div>

                    <div className="medication-data">
                      <div className="remaining-days">
                        <strong>
                          {Math.max(
                            0,
                            medication.remaining ?? 0
                          )}
                        </strong>

                        <span>estimated days remaining</span>
                      </div>

                      <div className="end-date">
                        <span>Estimated supply end</span>

                        <strong>
                          {medication.endDate
                            ? formatDate(medication.endDate)
                            : "Not available"}
                        </strong>
                      </div>
                    </div>

                    <div
                      className="supply-bar"
                      role="progressbar"
                      aria-label={`Estimated supply remaining for ${medication.name}`}
                      aria-valuemin="0"
                      aria-valuemax="100"
                      aria-valuenow={Math.round(
                        medication.percentage
                      )}
                    >
                      <span
                        className={`supply-fill fill-${status.kind}`}
                        style={{
                          width: `${medication.percentage}%`,
                        }}
                      />
                    </div>

                    <div className="medication-buttons">
                      <button
                        type="button"
                        className="button button-primary"
                        onClick={() =>
                          openCollectionForm(medication)
                        }
                      >
                        I've collected more
                      </button>

                      <button
                        type="button"
                        className="button button-outline"
                        onClick={() =>
                          archiveMedication(medication)
                        }
                      >
                        <Icon name="archive" size={18} />
                        Archive medication
                      </button>
                    </div>

                    <details className="collection-details">
                      <summary>
                        View collection history (
                        {medication.collections.length})
                      </summary>

                      <ul>
                        {[...medication.collections]
                          .reverse()
                          .map((entry) => (
                            <li key={entry.id}>
                              <span>
                                {formatDate(entry.date)}
                              </span>

                              <strong>
                                {entry.quantity} tablets
                              </strong>
                            </li>
                          ))}
                      </ul>
                    </details>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        {/* REMINDERS */}

        <section
          className="content-section wrap"
          id="reminders"
        >
          <div className="section-top">
            <div>
              <p className="overline">LOOKING AHEAD</p>
              <h2>Medication reminders</h2>

              <p className="section-subtitle">
                Gentle reminders to check your repeat prescription
                arrangements.
              </p>
            </div>

            <span className="section-icon">
              <Icon name="bell" size={26} />
            </span>
          </div>

          {reminders.length === 0 ? (
            <div className="clear-message">
              <span className="clear-symbol">
                <Icon name="check" size={25} />
              </span>

              <div>
                <h3>
                  Nothing needs your attention right now.
                </h3>

                <p>
                  In-app reminders appear when an estimated
                  supply reaches 14 days or fewer.
                </p>
              </div>
            </div>
          ) : (
            <div className="reminder-list">
              {reminders.map((medication) => (
                <article
                  className="reminder-item"
                  key={medication.id}
                >
                  <span className="reminder-symbol">
                    <Icon name="bell" size={25} />
                  </span>

                  <div>
                    <h3>
                      Time to check: {medication.name}
                    </h3>

                    <p>
                      {medication.remaining > 0
                        ? `Your estimated supply may end in ${medication.remaining} days.`
                        : "Your estimated supply end date has passed."}
                    </p>

                    <p>
                      Please check your repeat prescription
                      arrangements with your pharmacy.
                    </p>

                    <div className="action-row">
                      <button
                        type="button"
                        className="button button-primary"
                        onClick={() =>
                          openCollectionForm(medication)
                        }
                      >
                        I've collected more
                      </button>

                      <button
                        type="button"
                        className="button button-outline"
                        onClick={() =>
                          snoozeReminder(medication.id)
                        }
                      >
                        Remind me tomorrow
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        {/* MEDICATION ARCHIVE */}

        <section
          className="content-section wrap history-section"
          id="history"
        >
          <div className="section-top">
            <div>
              <p className="overline">YOUR RECORDS</p>
              <h2>Medication history</h2>

              <p className="section-subtitle">
                A place to keep previously tracked medications.
              </p>
            </div>

            <span className="section-icon">
              <Icon name="archive" size={27} />
            </span>
          </div>

          <label className="history-search">
            <Icon name="search" size={21} />

            <span className="sr-only">
              Search medication history
            </span>

            <input
              type="search"
              value={historySearch}
              onChange={(event) =>
                setHistorySearch(event.target.value)
              }
              placeholder="Search your medication history..."
            />
          </label>

          {archive.length === 0 ? (
            <div className="empty-state">
              <span className="empty-icon">
                <Icon name="history" size={31} />
              </span>

              <h3>Your history will appear here.</h3>

              <p>
                When you archive a medication, its details and
                recorded collections will be kept in this section.
              </p>
            </div>
          ) : filteredArchive.length === 0 ? (
            <p className="search-empty">
              No archived medications match your search.
            </p>
          ) : (
            <div className="archive-list">
              {filteredArchive.map((medication) => (
                <article
                  className="archive-item"
                  key={medication.id}
                >
                  <div className="archive-heading">
                    <span className="medication-symbol">
                      <Icon name="archive" size={25} />
                    </span>

                    <div>
                      <h3>{medication.name}</h3>

                      <p>
                        Archived{" "}
                        {formatDate(
                          medication.archivedAt || localDate()
                        )}
                      </p>
                    </div>

                    <span className="archive-badge">
                      Archived
                    </span>
                  </div>

                  <p className="archive-description">
                    Last recorded collection:{" "}
                    {formatDate(medication.collectionDate)}
                    {" · "}
                    {medication.quantity} tablets
                    {" · "}
                    {scheduleText(medication)}
                  </p>

                  <div className="action-row">
                    <button
                      type="button"
                      className="button button-outline"
                      aria-expanded={
                        expandedHistory === medication.id
                      }
                      onClick={() =>
                        setExpandedHistory((old) =>
                          old === medication.id
                            ? null
                            : medication.id
                        )
                      }
                    >
                      <Icon name="history" size={18} />

                      {expandedHistory === medication.id
                        ? "Hide collection history"
                        : "View collection history"}
                    </button>

                    <button
                      type="button"
                      className="button button-primary"
                      onClick={() =>
                        restoreMedication(medication)
                      }
                    >
                      Restore medication
                    </button>
                  </div>

                  {expandedHistory === medication.id && (
                    <div className="archive-collections">
                      <h4>Recorded collections</h4>

                      <ul>
                        {[...medication.collections]
                          .reverse()
                          .map((entry) => (
                            <li key={entry.id}>
                              <span>
                                {formatDate(entry.date)}
                              </span>

                              <strong>
                                {entry.quantity} tablets
                              </strong>
                            </li>
                          ))}
                      </ul>
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}

          <p className="history-note">
            These are your own records, not verified pharmacy or
            prescription records. Archiving stops refill reminders
            for that medication.
          </p>
        </section>

        {/* EMERGENCY DETAILS */}

        <section
          className="emergency-section wrap"
          id="emergency"
        >
          <div className="emergency-top">
            <div className="emergency-copy">
              <span className="emergency-mark">
                <Icon name="heart" size={27} />
              </span>

              <div>
                <p className="overline">
                  IMPORTANT INFORMATION
                </p>

                <h2>Emergency details, close at hand.</h2>

                <p>
                  Keep your contacts, allergies and important
                  notes in one easy-to-find place.
                </p>
              </div>
            </div>

            <button
              type="button"
              className="button button-light"
              aria-expanded={showEmergency}
              onClick={() =>
                setShowEmergency((old) => !old)
              }
            >
              {showEmergency
                ? "Hide details"
                : "View or edit details"}

              <Icon name="arrow" size={19} />
            </button>
          </div>

          {showEmergency && (
            <div className="emergency-details">
              <div className="emergency-warning">
                <Icon name="info" size={22} />

                <p>
                  These details are self-reported, not a verified
                  medical record. In a UK emergency, call 999.
                  Do not delay getting help to find this page.
                </p>
              </div>

              <div className="form-grid">
                {[
                  ["patientName", "Full name", "Your full name"],
                  [
                    "allergies",
                    "Allergies",
                    "e.g. Penicillin or none known",
                  ],
                  [
                    "contactName",
                    "Emergency contact name",
                    "Name",
                  ],
                  [
                    "contactPhone",
                    "Emergency contact phone",
                    "Telephone",
                  ],
                  [
                    "secondContactName",
                    "Second contact name",
                    "Optional",
                  ],
                  [
                    "secondContactPhone",
                    "Second contact phone",
                    "Optional",
                  ],
                ].map(([name, label, placeholder]) => (
                  <div className="field" key={name}>
                    <label htmlFor={name}>{label}</label>

                    <input
                      id={name}
                      name={name}
                      type={
                        name.toLowerCase().includes("phone")
                          ? "tel"
                          : "text"
                      }
                      value={emergency[name]}
                      onChange={(event) =>
                        setEmergency((old) => ({
                          ...old,
                          [event.target.name]:
                            event.target.value,
                        }))
                      }
                      placeholder={placeholder}
                    />
                  </div>
                ))}

                <div className="field full-field">
                  <label htmlFor="medicalNotes">
                    Important medical notes
                  </label>

                  <textarea
                    id="medicalNotes"
                    name="medicalNotes"
                    rows="3"
                    value={emergency.medicalNotes}
                    onChange={(event) =>
                      setEmergency((old) => ({
                        ...old,
                        medicalNotes: event.target.value,
                      }))
                    }
                    placeholder="Only enter information you're comfortable saving on this device."
                  />
                </div>
              </div>

              <div className="action-row">
                {emergency.contactPhone.trim() && (
                  <a
                    className="button button-primary"
                    href={telephone(emergency.contactPhone)}
                  >
                    <Icon name="phone" size={19} />

                    Call{" "}
                    {emergency.contactName ||
                      "emergency contact"}
                  </a>
                )}

                {emergency.secondContactPhone.trim() && (
                  <a
                    className="button button-primary"
                    href={telephone(
                      emergency.secondContactPhone
                    )}
                  >
                    <Icon name="phone" size={19} />

                    Call{" "}
                    {emergency.secondContactName ||
                      "second contact"}
                  </a>
                )}
              </div>

              <p className="privacy-note">
                Information saves in this browser and is not
                encrypted. Use fictional information for the
                hackathon demo.
              </p>
            </div>
          )}
        </section>

        {/* DEMO ASSISTANT */}

        <section
          className="content-section wrap chat-section"
          id="assistant"
        >
          <div className="section-top">
            <div>
              <p className="overline">A HELPING HAND</p>
              <h2>Ask medAssist AI</h2>

              <p className="section-subtitle">
                Tell me what you collected in your own words.
                I'll fill in the form for you to check.
              </p>
            </div>

            <span className="demo-tag">
              Powered by NVIDIA Nemotron
            </span>
          </div>

          <div className="chat-history" aria-live="polite">
            {messages.map((message, index) => (
              <div
                className={`chat-line ${message.role}`}
                key={index}
              >
                <span className="chat-icon">
                  {message.role === "assistant" ? (
                    <Icon name="heart" size={18} />
                  ) : (
                    "You"
                  )}
                </span>

                <p>{message.text}</p>
              </div>
            ))}

            {chatLoading && (
              <div className="chat-line assistant">
                <span className="chat-icon">
                  <Icon name="heart" size={18} />
                </span>
                <p>Thinking…</p>
              </div>
            )}
          </div>

          <form className="chat-form" onSubmit={sendMessage}>
            <label
              className="sr-only"
              htmlFor="chat-input"
            >
              Ask medAssist AI a question
            </label>

            <input
              id="chat-input"
              value={chatInput}
              onChange={(event) =>
                setChatInput(event.target.value)
              }
              placeholder="e.g. I collected 60 tablets of ExampleMed today, one a day"
              maxLength={1000}
            />

            <button
              className="button button-primary"
              type="submit"
              disabled={chatLoading}
            >
              Send
              <Icon name="arrow" size={18} />
            </button>
          </form>

          <p className="privacy-note">
            The assistant only fills in the form. Nothing is saved
            until you press Save. Use fictional medication names for
            the demo.
          </p>
        </section>

        {/* DISCLAIMER */}

        <aside className="disclaimer wrap">
          <Icon name="info" size={22} />

          <p>
            <strong>A note about medAssist AI:</strong>{" "}
            Supply dates assume every scheduled dose is taken and
            are only estimates. medAssist AI does not know whether
            tablets have actually been taken and does not provide
            medical advice. Calendar times are not notifications.
          </p>
        </aside>
      </main>

      {/* FOOTER */}

      <footer className="footer">
        <div className="wrap footer-inner">
          <strong>
            medAssist AI<span>.</span>
          </strong>

          <p>
            Thoughtfully designed for easier everyday medication
            management.
          </p>

          <small>
            Always follow guidance from your GP or pharmacist.
          </small>
        </div>
      </footer>

      {/* SAVE CONFIRMATION */}

      {toast && (
        <div className="toast" role="status">
          <Icon name="check" size={20} />
          {toast}
        </div>
      )}
    </div>
  );
}

export default App;