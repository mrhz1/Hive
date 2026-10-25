import { useState, useRef, useEffect, useMemo } from "react";
import { ChevronRight, ChevronLeft } from "lucide-react";
import calculateRiskAndLocationSummary from "./risk_locations.js";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Legend,
  ReferenceArea,
} from "recharts";
import dashboardQRImg from "../../assets/dashboard_qrcode.png";
import { usePatient } from "../../contexts/PatientContext";
import { useNavigate } from "react-router-dom";
import DOMPurify from "dompurify"; // npm install dompurify
import AllSurgeries from "../all-surgeries";

const DashboardPage = () => {
  const FEEDBACK_LINK = "https://redcap.link/ne483vl1";
  const { currentPatient, setSelectedCCSDBItem, selectedCCSDBItem } = usePatient();
  const navigate = useNavigate();
  const [showQR, setShowQR] = useState(false);

  //0 - bullet form summary, 1 - full summary
  // const [caseSummaryVer, setCaseSummaryVer] = useState(0);
  // const [similaritySummaryVer, setSimilaritySummaryVer] = useState(0);
  const [selectedSurgery, setSelectedSurgery] = useState(null);
  const [open, setOpen] = useState(false);
  const [pOpen, setPOpen] = useState(true);
  const [rOpen, setROpen] = useState(true);
  const [sOpen, setSOpen] = useState(true);
  const [cOpen, setCOpen] = useState(true);
  // const [paOpen, setPAOpen] = useState(true);
  const [caseAnalysisPatient, setCaseAnalysisPatient] = useState([]);
  const [caseAnalysisContent, setCaseAnalysisContent] = useState([]);
  const [similaritySummaryContent, setSimilaritySummaryContent] = useState([]);
  const ref = useRef(null);

  // Refs for each dashboard section
  const ai4dRef = useRef();
  // const summaryRef = useRef();
  // const similarityRef = useRef();

  // Navigate to patient search if no patient is selected
  useEffect(() => {
    if (!currentPatient) {
      navigate("/");
    }
  }, [currentPatient, navigate]);

  // Track previous patient ID to only reset indices when patient changes
  const prevPatientId = useRef(currentPatient?.id);

  useEffect(() => {
    if (currentPatient?.id !== prevPatientId.current) {
      prevPatientId.current = currentPatient?.id;
    }
  }, [currentPatient?.id]);

  // Close risk of surgical complications dropwdown on outside click
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const [filters, setFilters] = useState({});

  const sortedData = useMemo(() => {
    return (currentPatient?.allSurguries || [])
      .sort((a, b) => new Date(b.op_date) - new Date(a.op_date))
      .map((item, index) => ({
        ...item,
        id: index + 1,
      }));
  }, [currentPatient]);
  const filteredData = useMemo(() => {
    return sortedData.filter((item) => Object.entries(filters).every(([key, value]) => item[key] === value));
  }, [sortedData, filters]);

  useEffect(() => {
    if (currentPatient?.encounter) {
      setFilters({
        epic_csn_id: Number(currentPatient.encounter),
      });
    }
  }, [currentPatient?.encounter]);
  setSelectedCCSDBItem(filteredData[0] || null);

  const displayAge = (patientAge) => {
    const DAYS_IN_YEAR = 365;
    const DAYS_IN_MONTH = 30;

    if (patientAge == null) return "N/A";

    // Less than 1 month
    if (patientAge < DAYS_IN_MONTH) {
      return `${patientAge} day${patientAge !== 1 ? "s" : ""} old`;
    }

    // Less than 1 year
    if (patientAge < DAYS_IN_YEAR) {
      const months = Math.floor(patientAge / DAYS_IN_MONTH);
      return `${months} month${months !== 1 ? "s" : ""} old`;
    }

    // 1 year or more
    const years = Math.floor(patientAge / DAYS_IN_YEAR);
    const remainingDays = patientAge % DAYS_IN_YEAR;
    const months = Math.floor(remainingDays / DAYS_IN_MONTH);

    if (months === 0) {
      return `${years} year${years !== 1 ? "s" : ""} old`;
    }

    return `${years} year${years !== 1 ? "s" : ""} ${months} month${months !== 1 ? "s" : ""} old`;
  };
  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      const format6 = (num) => Number(num.toFixed(6));
      return (
        <div style={{ background: "#fff", padding: 10, border: "1px solid #ddd" }}>
          <p style={{ marginBottom: 8 }}>{data.subject}</p>

          {payload.map((entry, index) => (
            <div
              key={index}
              style={{
                display: "flex",
                justifyContent: "space-between",
                color: entry.stroke,
                fontWeight: 500,
              }}
            >
              <span className="pr-2">{entry.name}:</span>
              <span>{format6(data.hover[index].value) + " " + data.hover[index].units}</span>
            </div>
          ))}
        </div>
      );
    }

    return null;
  };

  // Destructure patient data
  const {
    ai4dlocations = [],
    ai4dGraphData = [],
    riskComplications = [],
    surgicalDataSets = [],
    summary = {},
    caseAnalysis = "",
    similarityData = [],
    similaritySummary = [],
    ccsdbDataArray = [],
  } = currentPatient || {};
  const surgicalDataSetsArray = Array.isArray(surgicalDataSets) ? surgicalDataSets : Object.values(surgicalDataSets);
  const filtering = (filters) => {
    setFilters(filters);
  };

  function formatDate(value) {
    if (!value) return null;
    const match = value.match(/^(\d{4})-(\d{2})-(\d{2})(.*)$/);
    if (!match) return value;
    const [, year, month, day, rest] = match;
    return `${day}-${month}-${year}${rest}`;
  }

  function getTypeValue(item) {
    if (item && item.includes(",")) {
      const [first, second] = item.split(",").map((part) => part.trim());
      return `${first} [${second}]`;
    }
    return item;
  }

  function formatText(text) {
    if (!text) return "";

    // Ensure text is a string
    text = String(text);

    // Parse the JSON string if it starts with '{"summary":'
    let parsedText = text;
    try {
      if (text.trim().startsWith('{"summary":')) {
        const json = JSON.parse(text); // Parse the JSON
        parsedText = json.summary || ""; // Extract the 'summary' key
      }
    } catch (error) {
      console.error("Error parsing case analysis JSON:", error);
    }

    // Ensure parsedText is a string
    let safeText = Array.isArray(parsedText) ? parsedText.join("\n") : String(parsedText);
    safeText = safeText.replace(/\\n/g, "\n");

    // Split into paragraphs by double newlines
    let html = safeText
      .split(/\n{2,}/)
      .map((para) => {
        // Bold
        let p = para.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
        // Numbered bullets
        p = p.replace(/^\s*\d+\.\s+(.*)$/gm, "<li>$1</li>");
        // Star bullets
        p = p.replace(/^\s*\*\s+(.*)$/gm, "<li>$1</li>");
        // If this paragraph contains list items, wrap in <ul>
        if (p.includes("<li>")) {
          return `<ul>${p}</ul>`;
        }
        // Otherwise, wrap in <p> and replace single newlines with <br>
        return `<p>${p.replace(/\n/g, "<br>")}</p>`;
      })
      .join("");

    return DOMPurify.sanitize(html);
  }

  const PHI = [
    { label: "PatientID", value: selectedCCSDBItem?.patient_id },
    { label: "Name", value: selectedCCSDBItem?.name },
    { label: "Epic csn.", value: selectedCCSDBItem?.epic_csn_id },
    { label: "Mrn", value: selectedCCSDBItem?.mrn },
    { label: "Birthdate", value: formatDate(selectedCCSDBItem?.birthdate) },
    { label: "Age at surgery", value: displayAge(selectedCCSDBItem?.age) },
    { label: "Sex", value: selectedCCSDBItem?.gender ?? "N/A" },
    { label: "Weight", value: selectedCCSDBItem?.weight },
    { label: "Height", value: selectedCCSDBItem?.height },
  ];

  const SI = [
    { label: "Type", value: getTypeValue(selectedCCSDBItem?.type) },
    { label: "Operation Date", value: formatDate(selectedCCSDBItem?.op_date) },
    { label: "Surgeon", value: selectedCCSDBItem?.surgeon },
    {
      label: "Cardiologist / Anesthesiologist",
      value: selectedCCSDBItem?.cardiologist ? selectedCCSDBItem?.cardiologist + " / " + selectedCCSDBItem?.anesthesiologist : "N/A",
    },
    { label: "Original Diagnosis (index)", value: ccsdbDataArray[0]?.primary_diagnosis },
    { label: "Current Primary Diagnosis", value: selectedCCSDBItem?.primary_diagnosis },
    { label: "Current Secondary Diagnosis", value: selectedCCSDBItem?.secondary_diagnoses },
    { label: "Primary Operation", value: selectedCCSDBItem?.primary_operation },
    { label: "Secondary Operation", value: selectedCCSDBItem?.secondary_operations },
    { label: "P/O Los", value: selectedCCSDBItem?.p_o_los },
  ];
  const tableColumns = ["Operation Date", "Encounter ID", "Type", "Primary Diagnosis", "Primary Operation", "Action"];
  const tableRows = sortedData.map((data, index) => [
    formatDate(data.op_date),
    data.enc_id ? data.enc_id : "N/A",
    getTypeValue(data.type),
    data.primary_diagnosis,
    data.primary_operation,
    <button
      className="box-border flex h-10 w-40 shrink-0 items-center justify-center rounded border bg-[#f1f1f4] hover:bg-slate-200 disabled:opacity-40 dark:bg-slate-800 dark:text-slate-50 dark:hover:bg-slate-700"
      onClick={() => {
        filtering({ id: data.id });
        setSelectedSurgery(index);
      }}
    >
      View
    </button>,
  ]);

  const locationColors = {
    "SK 4D": "#8AD260",
    "SK MAIN OR": "#514684",
    "SK CCCU": "#BF4140",
    "SK CDIU": "#E6863E",
    "SK OUTSIDE OF CARDIO": "#F1E94D",
  };
  const escapeRegex = (str) => str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  const keys = ["Patient", "Intra-op Echo", "Post-operative Course", "Pre-discharge Echo", "Discharge Status"];

  const keyPattern = keys.map(escapeRegex).join("|");

  const regex = new RegExp(`(?:\\*\\*(${keyPattern}):\\*\\*|(${keyPattern}):)\\s*(.*?)(?=\\n\\s*\\n|$)`, "gs");

  const matches = {};

  const regex1 = /\*\*(\d+\)\s*.*?)\*\*\s*([\s\S]*?)(?=\n\s*\*\*\d+\)|$)/g;

  useEffect(() => {
    if (!caseAnalysis?.bullet_form || !similaritySummary?.bullet_form) return;
    for (const match of caseAnalysis.bullet_form.matchAll(regex)) {
      const title = match[1] || match[2];
      const content = match[3].trim();

      matches[title] = content;
    }
    const case_analysis_summary = keys
      .filter((key) => matches[key] !== undefined)
      .map((key) => ({
        title: key,
        content: matches[key],
      }));
    const sections = [...similaritySummary.bullet_form.matchAll(regex1)].map((match) => ({
      title: match[1].trim(),
      content: match[2].trim(),
    }));
    setCaseAnalysisPatient(case_analysis_summary[0]);
    setCaseAnalysisContent(case_analysis_summary.slice(1));
    setSimilaritySummaryContent(sections);
  }, [caseAnalysis.bullet_form]);
  const ai4dData = calculateRiskAndLocationSummary(ai4dGraphData, ai4dlocations, locationColors);

  if (!currentPatient) return null;

  const HEIGHT = 300;
  const AXIS_HEIGHT = 54;
  const MARGIN = { top: 10, right: 10, bottom: 0, left: 15 };
  return (
    <div className="relative flex flex-col gap-y-6">
      {/* Patient information Bar */}
      <h1>salam</h1>
      <div className="w-full overflow-hidden rounded-lg border border-gray-200 bg-[#f1f1f4] shadow-sm dark:bg-slate-800">
        <button
          type="button"
          onClick={() => setPOpen(!pOpen)}
          className="flex w-full items-center justify-between px-4 py-3 text-left font-medium text-gray-800 transition-colors duration-200 hover:bg-gray-300"
        >
          <span className="font-semibold dark:text-neutral-300">Patient Information</span>

          <svg
            className={`h-5 w-5 text-gray-500 transition-transform duration-200 ease-out ${pOpen ? "rotate-180" : "rotate-0"}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </button>
        <div className={`grid bg-[#f1f1f4] transition-all duration-200 ease-out dark:bg-slate-800 ${pOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
          <div className="overflow-hidden">
            <div className="border-t border-gray-200 px-4 py-4">
              <div className="bg-box rounded-xl p-6 dark:bg-slate-800">
                <div className="border-b border-neutral-200 pb-3 dark:border-neutral-400">
                  <div className="mb-6 grid gap-x-4 gap-y-4 sm:grid-cols-2 lg:grid-cols-5">
                    {selectedCCSDBItem &&
                      PHI.slice(0, 4).map((item) => (
                        <div
                          key={item.label}
                          className={`flex max-w-full flex-col gap-1`}
                        >
                          <span className="pb-1 text-sm text-neutral-500 dark:text-neutral-300">{item.label}</span>
                          <span className="text-md dark:text-slate-50">{item.value ? item.value : "N/A"}</span>
                        </div>
                      ))}
                  </div>
                  <div className="mb-6 grid gap-x-4 gap-y-4 sm:grid-cols-2 lg:grid-cols-5">
                    {selectedCCSDBItem &&
                      PHI.slice(4).map((item) => (
                        <div
                          key={item.label}
                          className={`flex max-w-full flex-col gap-1`}
                        >
                          <span className="pb-1 text-sm text-neutral-500 dark:text-neutral-300">{item.label}</span>
                          <span className="text-md dark:text-slate-50">{item.value ? item.value : "N/A"}</span>
                        </div>
                      ))}
                  </div>
                </div>
                <div className="grid-col-span-1 my-6 grid gap-x-4 gap-y-4 border-b border-neutral-200 pb-3 dark:border-neutral-400 lg:grid-cols-3">
                  {selectedCCSDBItem &&
                    SI.map((item) => (
                      <div
                        key={item.label}
                        className={`flex max-w-full flex-col gap-1`}
                      >
                        <span className="pb-1 text-sm text-neutral-500 dark:text-neutral-300">{item.label}</span>
                        <span className="text-md dark:text-slate-50">{item.value ? item.value : "N/A"}</span>
                      </div>
                    ))}
                </div>
                <div className="grid-col-span-1 my-6 grid gap-x-4 gap-y-4">
                  <div className={`flex max-w-full flex-col gap-1 border-b border-neutral-200 pb-3 dark:border-neutral-400`}>
                    <span className="text-sm text-neutral-500 dark:text-neutral-300">Post-op Complications</span>
                    <div className="flex flex-wrap gap-x-3">
                      {summary?.complications?.map((item) => (
                        <span className="text-md my-2 w-fit rounded-xl border-gray-200 bg-gray-200 px-3 py-2 dark:bg-neutral-700 dark:text-slate-50">
                          {item}
                        </span>
                      )) ?? "N/A"}
                    </div>
                  </div>
                  <div className={`flex max-w-full flex-col gap-1 border-b border-neutral-200 pb-3 dark:border-neutral-400`}>
                    <span className="pb-1 text-sm text-neutral-500 dark:text-neutral-300">Comment</span>
                    <span className="text-md dark:text-slate-50">{selectedCCSDBItem?.comment ?? "N/A"}</span>
                  </div>
                </div>
              </div>
              <div className="p-4">
                <AllSurgeries
                  selectedSurgery={selectedSurgery}
                  TableColumnsSplit={tableColumns}
                  TableRowsSplit={tableRows}
                />
              </div>
              <div className="flex items-center gap-x-4 text-slate-900 dark:text-slate-50">
                <div className="ml-auto mt-auto">
                  <span className="mx-5 text-xs text-slate-400">generated by CCSDB</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Risk Quantification Graph */}
      <div className="w-full rounded-lg border border-gray-200 bg-[#f1f1f4] shadow-sm dark:bg-slate-800">
        <button
          type="button"
          onClick={() => setROpen(!rOpen)}
          className="flex w-full items-center justify-between px-4 py-3 text-left font-medium text-gray-800 transition-colors duration-200 hover:bg-gray-300"
        >
          <span className="font-semibold dark:text-neutral-300">Risk of Returning to/Staying in CCCU Within 24 Hours (Admission to Discharge)</span>

          <svg
            className={`h-5 w-5 text-gray-500 transition-transform duration-200 ease-out ${rOpen ? "rotate-180" : "rotate-0"}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </button>
        <div className={`grid transition-all duration-200 ease-out ${rOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
          <div className="overflow-hidden">
            <div
              ref={ai4dRef}
              className={"flex flex-col p-4 shadow transition-all duration-300 dark:bg-slate-800"}
            >
              {ai4dData?.riskData.length > 0 ? (
                <>
                  <div className="-ml-10 mt-1 grid h-full grid-cols-1 items-center text-slate-400 dark:text-slate-50 lg:grid-cols-[70%_30%]">
                    <div className="h-full">
                      <ResponsiveContainer
                        width="100%"
                        height={HEIGHT}
                      >
                        <LineChart
                          data={ai4dData.riskData}
                          margin={MARGIN}
                        >
                          <defs>
                            <linearGradient
                              id="riskRamp"
                              gradientUnits="userSpaceOnUse"
                              x1="0"
                              y1={MARGIN.top}
                              x2="0"
                              y2={HEIGHT - AXIS_HEIGHT}
                            >
                              <stop
                                offset="0%"
                                stopColor="#C2452C"
                              />
                              <stop
                                offset="50%"
                                stopColor="#C98A00"
                              />
                              <stop
                                offset="100%"
                                stopColor="#0F6E68"
                              />
                            </linearGradient>
                          </defs>
                          <CartesianGrid
                            stroke="#E8E5DF"
                            vertical={false}
                          />
                          {ai4dData.locationSummary.map((item) => (
                            <ReferenceArea
                              x1={item.x1 * 6}
                              x2={item.x2 * 6}
                              y1={item.y1}
                              y2={item.y2}
                              fill={item.fill}
                              fillOpacity={item.fillOpacity}
                            />
                          ))}
                          <XAxis
                            type="number"
                            dataKey="hour"
                            domain={[0, Math.max(...ai4dData.riskData.map((d) => Number(d.hour)))]}
                            ticks={ai4dData.riskData.map((d) => Number(d.hour)).filter((h) => h % 24 === 0)}
                            tickFormatter={(h) => `Day ${h / 24}`}
                          />
                          <YAxis />
                          <Tooltip
                            labelFormatter={() => ""}
                            formatter={(value, name, props) => {
                              const full = props?.payload;
                              const top5 = full?.top5Contributions;
                              const location = full?.dept_name;
                              return [
                                <>
                                  {value}
                                  {top5 && (
                                    <>
                                      <br />
                                      <span style={{ color: "#6b7280" }}>
                                        {top5.map((item) => (
                                          <div>{item}</div>
                                        ))}
                                      </span>
                                    </>
                                  )}
                                  {location && (
                                    <>
                                      <span style={{ color: "#6b7280" }}>
                                        <div>location: {location}</div>
                                      </span>
                                    </>
                                  )}
                                </>,
                                name,
                              ];
                            }}
                          />
                          <Line
                            type="linear"
                            dataKey="risk"
                            stroke="url(#riskRamp)"
                            strokeOpacity={1}
                            strokeWidth={3.5}
                            dot={false}
                            isAnimationActive={false}
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="grid place-items-center">
                      <div>
                        {Object.entries(locationColors).map(([label, color]) => (
                          <div
                            key={label}
                            className="flex items-center gap-5"
                          >
                            <div
                              className="h-4 w-4 rounded-sm border border-gray-300"
                              style={{ backgroundColor: color, opacity: "0.4" }}
                            />
                            <span className="text-[20px] text-neutral-500 dark:text-neutral-300">{label}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                  <div
                    className="mt-4 inline-block"
                    ref={ref}
                  >
                    {/* Dropdown */}
                    <button
                      onClick={() => setOpen((prev) => !prev)}
                      className="flex items-center gap-2 rounded-md bg-slate-200 px-4 py-2 text-sm hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-50 dark:hover:bg-slate-600"
                    >
                      Risk of Surgical Complications
                      <svg
                        className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth="2"
                          d="M19 9l-7 7-7-7"
                        />
                      </svg>
                    </button>
                    {open && (
                      <div className="absolute left-0 z-50 mt-2 w-64 rounded-md border border-slate-200 bg-white shadow-lg">
                        <div className="divide-y text-sm text-slate-700">
                          {riskComplications.map(({ label, value }, index) => (
                            <div
                              key={index}
                              className="flex justify-between px-4 py-2"
                            >
                              <span className="text-slate-500">{label}</span>
                              <span className="font-medium">{value}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                "N/A"
              )}

              <span className="relative bottom-2 right-2 mt-2 text-right text-xs text-slate-400">Generated by AI4D</span>
            </div>
          </div>
        </div>
      </div>

      {/* Spider Chart */}
      <div className="w-full overflow-hidden rounded-lg border border-gray-200 bg-[#f1f1f4] shadow-sm dark:bg-slate-800">
        <button
          type="button"
          onClick={() => setSOpen(!sOpen)}
          className="flex w-full items-center justify-between px-4 py-3 text-left font-medium text-gray-800 transition-colors duration-200 hover:bg-gray-300"
        >
          <span className="font-semibold dark:text-neutral-300">
            Procedure Details: {summary.primary_operation ? summary.primary_operation + "[" + summary.enc_id + "]" : "N/A"}
          </span>

          <svg
            className={`h-5 w-5 text-gray-500 transition-transform duration-200 ease-out ${sOpen ? "rotate-180" : "rotate-0"}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </button>
        <div className={`grid transition-all duration-200 ease-out ${sOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
          <div className="overflow-hidden">
            <div
              ref={ai4dRef}
              className="relative flex w-full flex-col bg-[#f1f1f4] p-4 shadow transition-all duration-300 dark:bg-slate-800"
            >
              {similarityData.length > 0 ? (
                <div className="grid grid-cols-[60%_40%] px-6">
                  <div className="flex">
                    <ResponsiveContainer
                      width="100%"
                      height={300}
                    >
                      <RadarChart
                        className="pb-2"
                        cx="50%"
                        cy="45%"
                        outerRadius="85%"
                        data={similarityData || []}
                      >
                        <PolarGrid />
                        <PolarAngleAxis
                          dataKey="subject"
                          tick={(props) => {
                            const { x, y, payload } = props;
                            const lines = payload.value.split("\n");
                            return (
                              <text
                                x={x}
                                y={y}
                                textAnchor="middle"
                                fontSize={14}
                                fill="currentColor"
                                className="text-slate-700 dark:text-slate-50"
                                transform={`rotate(8, ${x}, ${y})`}
                              >
                                {lines.map((line, i) => (
                                  <tspan
                                    key={i}
                                    x={x}
                                    dy={i === 0 ? 0 : 16}
                                    dominantBaseline="middle"
                                  >
                                    {line}
                                  </tspan>
                                ))}
                              </text>
                            );
                          }}
                        />
                        <PolarRadiusAxis
                          angle={30}
                          domain={[0, 1]}
                        />
                        <Radar
                          name="This patient"
                          dataKey="This"
                          stroke="#f407a9"
                          fill="#f407a9"
                          fillOpacity={0.4}
                        />
                        <Radar
                          name={"Typical alike (top 1% , " + similarityData[0].counts + " patients )"}
                          dataKey="Typical"
                          stroke="#36d4e2"
                          fill="#36d4e2"
                          fillOpacity={0.3}
                        />
                        <Tooltip
                          content={<CustomTooltip />}
                          allowEscapeViewBox={{ x: true, y: true }}
                        />
                        <Legend
                          verticalAlign="bottom"
                          align="center"
                          layout="vertical"
                          height={40}
                          wrapperStyle={{ fontSize: "20px" }}
                        />
                      </RadarChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="flex items-center">
                    <ul className="py-auto text-xs text-slate-700 dark:text-slate-50">
                      {surgicalDataSetsArray.map((item, idx) => (
                        <li
                          key={idx}
                          className="grid grid-cols-2 py-2"
                        >
                          <span className="w-full break-words text-[16px] font-semibold">{item.label}</span>
                          <span className="whitespace-pre-line break-words text-right text-[16px]">{item.value}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              ) : (
                "N/A"
              )}

              <span className="absolute bottom-2 right-2 mt-2 text-right text-xs text-slate-400">Generated by ICAI2N</span>
            </div>
          </div>
        </div>
      </div>

      {/* Case Analysis */}
      <div className="w-full overflow-hidden rounded-lg border border-gray-200 bg-[#f1f1f4] shadow-sm dark:bg-slate-800">
        <button
          type="button"
          onClick={() => setCOpen(!cOpen)}
          className="flex w-full items-center justify-between px-4 py-3 text-left font-medium text-gray-800 transition-colors duration-200 hover:bg-gray-300"
        >
          <span className="font-semibold dark:text-neutral-300">Case Analysis</span>

          <svg
            className={`h-5 w-5 text-gray-500 transition-transform duration-200 ease-out ${cOpen ? "rotate-180" : "rotate-0"}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </button>
        <div className={`grid transition-all duration-200 ease-out ${cOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
          <div className="overflow-hidden">
            {/* Patient box */}
            <div className="m-4 overflow-hidden rounded-lg border border-gray-200 bg-gray-200 p-4 shadow-sm dark:bg-slate-800">
              <p className="mb-3 font-semibold dark:text-neutral-300">Case Overview</p>
              <div
                className="overflow-y-auto dark:text-slate-50"
                dangerouslySetInnerHTML={{ __html: formatText(caseAnalysisPatient.content) }}
              />
              {/* <span className="dark:text-slate-50">{caseAnalysisPatient.content}</span> */}
            </div>
            <div className="grid grid-cols-2">
              {/* Intra-op Echo */}
              {caseAnalysisContent.map((item) => (
                <div className="m-4 overflow-hidden rounded-lg border border-gray-200 bg-gray-200 p-4 shadow-sm dark:bg-slate-800">
                  <p className="mb-3 font-semibold dark:text-neutral-300">{item.title}</p>
                  <div
                    className="overflow-y-auto dark:text-slate-50"
                    dangerouslySetInnerHTML={{ __html: formatText(item.content) }}
                  />
                  {/* <span className="dark:text-slate-50">{item.content}</span> */}
                </div>
              ))}
              {similaritySummaryContent.map((item, index) => (
                <div className="m-4 overflow-hidden rounded-lg border border-gray-200 bg-gray-200 p-4 shadow-sm dark:bg-slate-800">
                  <p className="mb-3 font-semibold dark:text-neutral-300">{index == 0 ? "Outcome Comparison" : "Comparison Contributors"}</p>
                  <div
                    className="overflow-y-auto dark:text-slate-50"
                    dangerouslySetInnerHTML={{ __html: formatText(item.content) }}
                  />
                  {/* <span className="dark:text-slate-50">{item.content.replace(/[/*]/g, "")}</span> */}
                </div>
              ))}
            </div>
            {/* <div
              ref={summaryRef}
              className="relative min-h-0 overflow-hidden bg-[#f1f1f4] p-6 shadow transition-all duration-300 dark:bg-slate-800 md:col-span-3"
            >
              <div className="mb-2 flex justify-end">
                {caseAnalysis != null ? (
                  <div className="flex items-center gap-2">
                    <button
                      className="rounded p-1 hover:bg-slate-200 disabled:opacity-40 dark:hover:bg-slate-700"
                      onClick={(e) => {
                        e.stopPropagation();
                        setCaseSummaryVer((i) => Math.max(i - 1, 0));
                      }}
                      disabled={caseSummaryVer === 0}
                      aria-label="Bullet form summary"
                    >
                      <ChevronLeft className="h-5 w-5 dark:text-slate-50" />
                    </button>
                    <button
                      className="rounded p-1 hover:bg-slate-200 disabled:opacity-40 dark:hover:bg-slate-700"
                      onClick={(e) => {
                        e.stopPropagation();
                        setCaseSummaryVer((i) => Math.min(i + 1, 1));
                      }}
                      disabled={caseSummaryVer === 1}
                      aria-label="Full summary"
                    >
                      <ChevronRight className="h-5 w-5 dark:text-slate-50" />
                    </button>
                  </div>
                ) : (
                  ""
                )}
              </div>
              {caseAnalysis ? (
                <div className="min-h-0">
                  <div
                    className="my-2 h-80 min-h-0 overflow-y-auto text-sm text-slate-800 dark:text-slate-50"
                    dangerouslySetInnerHTML={{ __html: formatText(caseSummaryVer === 0 ? caseAnalysis.bullet_form : caseAnalysis.summary) }}
                  />
                </div>
              ) : (
                "N/A"
              )}
              <span className="absolute bottom-3 right-4 mt-3 text-right text-xs text-slate-400">Generated by ICAI2N</span>
            </div> */}
          </div>
        </div>
      </div>

      {/* Population Similarity */}
      {/* <div className="w-full overflow-hidden rounded-lg border border-gray-200 bg-[#f1f1f4] shadow-sm dark:bg-slate-800">
        <button
          type="button"
          onClick={() => setPAOpen(!paOpen)}
          className="flex w-full items-center justify-between px-4 py-3 text-left font-medium text-gray-800 transition-colors duration-200 hover:bg-gray-300"
        >
          <span className="font-semibold">Population Similarity</span>

          <svg
            className={`h-5 w-5 text-gray-500 transition-transform duration-200 ease-out ${paOpen ? "rotate-180" : "rotate-0"}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </button>
        <div className={`grid transition-all duration-200 ease-out ${paOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
          <div className="overflow-hidden">
            <div
              ref={similarityRef}
              className="relative -mt-2 w-full rounded-2xl bg-[#f1f1f4] p-6 shadow transition-all dark:bg-slate-800 md:flex-row"
            >
              <div className="mb-2 flex justify-end">
                {similaritySummary != null ? (
                  <div className="flex items-center gap-2">
                    <button
                      className="rounded p-1 hover:bg-slate-200 disabled:opacity-40 dark:hover:bg-slate-700"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSimilaritySummaryVer((i) => Math.max(i - 1, 0));
                      }}
                      disabled={similaritySummaryVer === 0}
                      aria-label="Bullet form summary"
                    >
                      <ChevronLeft className="h-5 w-5 dark:text-slate-50" />
                    </button>
                    <button
                      className="rounded p-1 hover:bg-slate-200 disabled:opacity-40 dark:hover:bg-slate-700"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSimilaritySummaryVer((i) => Math.min(i + 1, 1));
                      }}
                      disabled={similaritySummaryVer === 1}
                      aria-label="Full summary"
                    >
                      <ChevronRight className="h-5 w-5 dark:text-slate-50" />
                    </button>
                  </div>
                ) : (
                  ""
                )}
              </div>
              {similaritySummary != null ? (
                <div className="flex flex-1 flex-col justify-center">
                  <div
                    className="h-80 space-y-1 overflow-y-auto pr-2 text-sm text-slate-800 dark:text-slate-50"
                    dangerouslySetInnerHTML={{
                      __html: `${formatText(similaritySummaryVer === 0 ? similaritySummary.bullet_form : similaritySummary.summary)}<br><br>`,
                    }}
                  />
                </div>
              ) : (
                "N/A"
              )}
              <span className="absolute bottom-3 right-4 mt-3 text-right text-xs text-slate-400">Generated by ICAI2N</span>
            </div>
          </div>
        </div>
      </div> */}

      <div className="mt-4 text-center text-sm">
        <button
          onClick={() => setShowQR(true)}
          className="text-blue-600 hover:underline dark:text-blue-400"
        >
          Feedback survey
        </button>
      </div>
      {showQR && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => setShowQR(false)}
        >
          <div
            className="relative rounded-lg bg-white p-6 shadow-xl dark:bg-slate-900"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              aria-label="Close"
              onClick={() => setShowQR(false)}
              className="absolute right-2 top-2 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
            >
              ✕
            </button>
            <a
              href={FEEDBACK_LINK}
              target="_blank"
              rel="noopener noreferrer"
              // className="inline-block select-all rounded-lg border border-blue-300 bg-blue-100 px-4 py-2 font-mono text-lg text-blue-700 transition hover:bg-blue-200 dark:border-blue-700 dark:bg-blue-900 dark:text-blue-200 dark:hover:bg-blue-800 md:text-2xl"
              style={{ wordBreak: "break-all" }}
            >
              <img
                src={dashboardQRImg}
                alt="Feedback survey QR code"
                className="mx-auto h-40"
                draggable={false}
              />
            </a>

            <p className="mt-3 text-center text-sm text-slate-600 dark:text-slate-300">Scan to complete the feedback survey</p>
          </div>
        </div>
      )}
    </div>
  );
};

export default DashboardPage;
