import { useEffect, useRef, useState } from "react";

const API_BASE = "http://localhost:8000";
const POLL_INTERVAL_MS = 1500;
const ACTIVE_STATUSES = ["queued", "ocr_processing", "embedding"];

const STATUS_LABELS = {
  queued: "Queued",
  ocr_processing: "OCR Processing",
  embedding: "Embedding",
  done: "Done",
  failed: "Failed",
};

function StatusBadge({ status }) {
  return (
    <span className={`badge badge-${status}`}>
      {STATUS_LABELS[status] || status}
    </span>
  );
}

function ProgressBar({ current, total }) {
  if (!total) return null;
  const pct = Math.min(100, Math.round((current / total) * 100));
  return (
    <div className="progress-wrap">
      <div className="progress-bar" style={{ width: `${pct}%` }} />
      <span className="progress-label">
        page {current} of {total}
      </span>
    </div>
  );
}

export default function App() {
  const [pendingFiles, setPendingFiles] = useState([]);
  const [jobs, setJobs] = useState([]); // { job_id, filename, status, current, total, error }
  const [isUploading, setIsUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  const [resultModal, setResultModal] = useState(null); // { filename, text } | null

  const [question, setQuestion] = useState("");
  const [selectedJobIds, setSelectedJobIds] = useState([]);
  const [isAsking, setIsAsking] = useState(false);
  const [askResult, setAskResult] = useState(null); // { answer, sources }
  const [askError, setAskError] = useState(null);

  const fileInputRef = useRef(null);

  // Poll status for any job that isn't finished yet.
  useEffect(() => {
    const jobsToPoll = jobs.filter((j) => ACTIVE_STATUSES.includes(j.status));
    if (jobsToPoll.length === 0) return;

    const interval = setInterval(async () => {
      for (const job of jobsToPoll) {
        try {
          const res = await fetch(`${API_BASE}/status/${job.job_id}`);
          if (!res.ok) continue;
          const data = await res.json();
          setJobs((prev) =>
            prev.map((j) =>
              j.job_id === job.job_id
                ? {
                    ...j,
                    status: data.status,
                    current: data.current || 0,
                    total: data.total || 0,
                    error: data.error || null,
                  }
                : j
            )
          );
        } catch {
          // network hiccup - just try again on the next tick
        }
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [jobs]);

  function handleFilesSelected(fileList) {
    const pdfFiles = Array.from(fileList).filter((f) =>
      f.name.toLowerCase().endsWith(".pdf")
    );
    setPendingFiles(pdfFiles);
  }

  function handleDrop(e) {
    e.preventDefault();
    setIsDragging(false);
    handleFilesSelected(e.dataTransfer.files);
  }

  async function handleUpload() {
    if (pendingFiles.length === 0) return;
    setIsUploading(true);

    const formData = new FormData();
    pendingFiles.forEach((file) => formData.append("files", file));

    try {
      const res = await fetch(`${API_BASE}/upload`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) throw new Error(`Upload failed (${res.status})`);
      const data = await res.json();

      const newJobs = data
        .filter((item) => item.job_id)
        .map((item) => ({
          job_id: item.job_id,
          filename: item.filename,
          status: item.status.startsWith("queued") ? "queued" : "failed",
          current: 0,
          total: 0,
          error: item.status.startsWith("queued") ? null : item.status,
        }));

      setJobs((prev) => [...prev, ...newJobs]);
      setPendingFiles([]);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      alert(`Upload failed: ${err.message}`);
    } finally {
      setIsUploading(false);
    }
  }

  async function viewResult(job) {
    try {
      const res = await fetch(`${API_BASE}/result/${job.job_id}`);
      if (!res.ok) throw new Error(`Could not load result (${res.status})`);
      const data = await res.json();
      setResultModal({ filename: data.filename, text: data.text });
    } catch (err) {
      alert(err.message);
    }
  }

  function toggleJobSelection(jobId) {
    setSelectedJobIds((prev) =>
      prev.includes(jobId) ? prev.filter((id) => id !== jobId) : [...prev, jobId]
    );
  }

  async function handleAsk(e) {
    e.preventDefault();
    if (!question.trim()) return;

    setIsAsking(true);
    setAskError(null);
    setAskResult(null);

    try {
      const res = await fetch(`${API_BASE}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          job_ids: selectedJobIds.length > 0 ? selectedJobIds : null,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
      setAskResult(data);
    } catch (err) {
      setAskError(err.message);
    } finally {
      setIsAsking(false);
    }
  }

  const doneJobs = jobs.filter((j) => j.status === "done");

  return (
    <div className="app">
      <header className="app-header">
        <h1>PDF OCR + RAG</h1>
        <p className="subtitle">
          Upload PDFs, OCR them asynchronously, then ask questions about their content.
        </p>
      </header>

      <section className="card">
        <h2>1. Upload PDFs</h2>
        <div
          className={`dropzone ${isDragging ? "dropzone-active" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            multiple
            hidden
            onChange={(e) => handleFilesSelected(e.target.files)}
          />
          <p>Drag & drop PDFs here, or click to browse</p>
          {pendingFiles.length > 0 && (
            <ul className="pending-file-list">
              {pendingFiles.map((f) => (
                <li key={f.name}>{f.name}</li>
              ))}
            </ul>
          )}
        </div>
        <button
          className="btn btn-primary"
          disabled={pendingFiles.length === 0 || isUploading}
          onClick={handleUpload}
        >
          {isUploading ? "Uploading..." : "Upload & Process"}
        </button>
      </section>

      {jobs.length > 0 && (
        <section className="card">
          <h2>2. Processing status</h2>
          <div className="job-grid">
            {jobs.map((job) => (
              <div className="job-card" key={job.job_id}>
                <div className="job-card-header">
                  <span className="filename" title={job.filename}>
                    {job.filename}
                  </span>
                  <StatusBadge status={job.status} />
                </div>

                {ACTIVE_STATUSES.includes(job.status) && (
                  <ProgressBar current={job.current} total={job.total} />
                )}

                {job.status === "failed" && job.error && (
                  <p className="error-text">{job.error}</p>
                )}

                {job.status === "done" && (
                  <div className="job-card-actions">
                    <button className="btn btn-secondary" onClick={() => viewResult(job)}>
                      View extracted text
                    </button>
                    <label className="checkbox-label">
                      <input
                        type="checkbox"
                        checked={selectedJobIds.includes(job.job_id)}
                        onChange={() => toggleJobSelection(job.job_id)}
                      />
                      Include in question search
                    </label>
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {doneJobs.length > 0 && (
        <section className="card">
          <h2>3. Ask a question</h2>
          <p className="hint">
            {selectedJobIds.length > 0
              ? `Searching within ${selectedJobIds.length} selected document(s).`
              : "No documents selected above — searching across all indexed documents."}
          </p>
          <form className="ask-form" onSubmit={handleAsk}>
            <input
              type="text"
              placeholder="Ask something about your documents..."
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />
            <button className="btn btn-primary" type="submit" disabled={isAsking}>
              {isAsking ? "Thinking..." : "Ask"}
            </button>
          </form>

          {askError && <p className="error-text">{askError}</p>}

          {askResult && (
            <div className="answer-block">
              <h3>Answer</h3>
              <p>{askResult.answer}</p>

              {askResult.sources?.length > 0 && (
                <>
                  <h4>Sources</h4>
                  <ul className="sources-list">
                    {askResult.sources.map((src, i) => (
                      <li key={i}>
                        <div className="source-header">
                          <strong>{src.filename}</strong>
                          <span className="score">score {src.score.toFixed(3)}</span>
                        </div>
                        <p className="source-chunk">{src.chunk_text}</p>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </section>
      )}

      {resultModal && (
        <div className="modal-overlay" onClick={() => setResultModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{resultModal.filename}</h3>
              <button className="btn-close" onClick={() => setResultModal(null)}>
                ×
              </button>
            </div>
            <pre className="modal-text">{resultModal.text}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
