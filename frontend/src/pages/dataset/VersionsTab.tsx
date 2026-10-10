import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, GitCompare, RefreshCw, ShieldCheck, Upload } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Dropzone } from "@/components/common/Dropzone";
import { MonitoringResult, type MonitoringOutcome } from "@/components/common/MonitoringResult";
import { Badge, StatusBadge } from "@/components/ui/Badge";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Callout, ErrorState, Field, LoadingBlock, Panel, Select, Textarea } from "@/components/ui/primitives";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { API_URL, ApiError, getToken, get, post, upload } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtBytes, fmtDate, fmtInt, humanize } from "@/lib/format";
import type { Dataset, Paged, Version } from "@/lib/types";

async function download(v: Version, name: string) {
  const res = await fetch(`${API_URL}/api/v1/versions/${v.id}/download`, { headers: { Authorization: `Bearer ${getToken()}` } });
  if (!res.ok) throw new Error("Download failed");
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${name}_v${v.version_number}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function UploadVersionDialog({ ds, open, onClose }: { ds: Dataset; open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [encoding, setEncoding] = useState("utf-8");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MonitoringOutcome | null>(null);
  const close = () => {
    setFile(null);
    setResult(null);
    setError(null);
    onClose();
  };
  const submit = async () => {
    if (!file) return setError("Choose a file.");
    setError(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("encoding", encoding);
    setProgress(0);
    try {
      const r = await upload<{ version: Version; monitoring: MonitoringOutcome }>(`/datasets/${ds.id}/versions`, fd, setProgress);
      setResult(r.monitoring);
      void qc.invalidateQueries();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Upload failed.");
    } finally {
      setProgress(null);
    }
  };
  return (
    <Dialog
      open={open}
      onClose={close}
      size="lg"
      title={`New version of ${ds.name}`}
      description="The file is profiled, validated against the rules, compared with the reference version and tested for drift."
      footer={
        result ? (
          <Button variant="primary" onClick={close}>
            Done
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={close}>
              Cancel
            </Button>
            <Button variant="primary" onClick={submit} loading={progress !== null} icon={<Upload className="h-4 w-4" />}>
              Upload and monitor
            </Button>
          </>
        )
      }
    >
      {result ? (
        <MonitoringResult result={result} datasetId={ds.id} />
      ) : (
        <div className="space-y-4">
          {error && (
            <Callout tone="crit" className="py-2">
              <span role="alert">{error}</span>
            </Callout>
          )}
          {ds.settings?.gate_mode === "block" && (
            <Callout tone="info" icon={<ShieldCheck className="h-4 w-4" />}>
              This dataset uses a blocking validation gate: a version with critical findings is quarantined and does not become active.
            </Callout>
          )}
          <Dropzone file={file} onFile={setFile} progress={progress} disabled={progress !== null} />
          <Field label="Text encoding" htmlFor="v_enc">
            <Select id="v_enc" value={encoding} onChange={(e) => setEncoding(e.target.value)}>
              <option value="utf-8">UTF-8</option>
              <option value="latin-1">Latin-1 (ISO-8859-1)</option>
            </Select>
          </Field>
        </div>
      )}
    </Dialog>
  );
}

export function VersionsTab({ ds }: { ds: Dataset }) {
  const qc = useQueryClient();
  const { can } = useAuth();
  const [page, setPage] = useState(1);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [promote, setPromote] = useState<Version | null>(null);
  const [note, setNote] = useState("");
  const versions = useQuery({ queryKey: ["versions", ds.id, page], queryFn: () => get<Paged<Version>>(`/datasets/${ds.id}/versions?page=${page}&page_size=20`) });

  const monitor = useMutation({
    mutationFn: (v: Version) => post<MonitoringOutcome>(`/versions/${v.id}/monitor`),
    onSuccess: (r) => {
      toast.success(`Monitoring finished with ${r.findings.length} finding(s).`);
      void qc.invalidateQueries();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Monitoring failed."),
  });
  const doPromote = useMutation({
    mutationFn: () => post(`/versions/${promote!.id}/promote`, { note }),
    onSuccess: () => {
      toast.success(`v${promote!.version_number} is now the active version.`);
      setPromote(null);
      setNote("");
      void qc.invalidateQueries();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not promote the version."),
  });

  return (
    <>
      <Panel
        title="Version history"
        description="Versions are immutable. Remediations that change data write a new derived version and keep the original."
        actions={
          <>
            {(ds.version_count ?? 0) >= 2 && (
              <ButtonLink size="sm" to={`/datasets/${ds.id}/compare`} icon={<GitCompare className="h-3.5 w-3.5" />}>
                Compare
              </ButtonLink>
            )}
            {can("editor") && (
              <Button size="sm" variant="primary" icon={<Upload className="h-3.5 w-3.5" />} onClick={() => setUploadOpen(true)}>
                Upload new version
              </Button>
            )}
          </>
        }
        bodyClassName="p-0"
      >
        {versions.isError ? (
          <ErrorState error={versions.error} retry={() => versions.refetch()} />
        ) : !versions.data ? (
          <div className="p-4">
            <LoadingBlock />
          </div>
        ) : (
          <>
            <Table label="Versions">
              <thead>
                <tr>
                  <Th>Version</Th>
                  <Th>Status</Th>
                  <Th>Origin</Th>
                  <Th align="right">Rows</Th>
                  <Th align="right">Cols</Th>
                  <Th align="right">Size</Th>
                  <Th>Created</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {versions.data.items.map((v) => (
                  <Tr key={v.id}>
                    <Td>
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-medium">v{v.version_number}</span>
                        {v.id === ds.reference_version_id && <Badge tone="accent">reference</Badge>}
                        {v.id === ds.current_version_id && <Badge tone="ok">active</Badge>}
                        {v.is_known_good && <Badge title="Passed monitoring without critical findings">known good</Badge>}
                      </div>
                      <div className="max-w-[260px] truncate text-xs text-faint" title={v.original_filename ?? ""}>
                        {v.original_filename}
                      </div>
                    </Td>
                    <Td>
                      <StatusBadge status={v.ingestion_status === "failed" ? "failed" : v.status} label={v.ingestion_status === "failed" ? "ingestion failed" : undefined} />
                      {v.ingestion_error && <div className="mt-1 max-w-[240px] text-xs text-crit">{v.ingestion_error.message}</div>}
                    </Td>
                    <Td className="text-sm text-muted">
                      {humanize(v.origin)}
                      {v.parent_version_id && <div className="text-xs text-faint">derived from #{v.parent_version_id}</div>}
                    </Td>
                    <Td align="right" mono>
                      {fmtInt(v.row_count)}
                    </Td>
                    <Td align="right" mono>
                      {fmtInt(v.column_count)}
                    </Td>
                    <Td align="right" mono className="text-muted">
                      {fmtBytes(v.size_bytes)}
                    </Td>
                    <Td className="whitespace-nowrap text-sm text-muted">{fmtDate(v.created_at)}</Td>
                    <Td align="right" className="whitespace-nowrap">
                      {v.ingestion_status === "succeeded" && (
                        <Button size="icon" variant="ghost" aria-label={`Download v${v.version_number} as CSV`} title="Download CSV" onClick={() => download(v, ds.name).catch(() => toast.error("Download failed."))}>
                          <Download className="h-3.5 w-3.5" />
                        </Button>
                      )}
                      {can("editor") && v.ingestion_status === "succeeded" && (
                        <Button size="icon" variant="ghost" aria-label={`Re-run monitoring on v${v.version_number}`} title="Re-run monitoring" loading={monitor.isPending && monitor.variables?.id === v.id} onClick={() => monitor.mutate(v)}>
                          {!(monitor.isPending && monitor.variables?.id === v.id) && <RefreshCw className="h-3.5 w-3.5" />}
                        </Button>
                      )}
                      {can("editor") && v.id !== ds.current_version_id && v.ingestion_status === "succeeded" && (
                        <Button size="sm" variant="ghost" onClick={() => setPromote(v)}>
                          Make active
                        </Button>
                      )}
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <div className="border-t border-line">
              <Pagination page={versions.data.page} pages={versions.data.pages} total={versions.data.total} onPage={setPage} />
            </div>
          </>
        )}
      </Panel>
      {(ds.version_count ?? 0) >= 2 && (
        <p className="mt-3 text-sm text-muted">
          Need the field-level differences?{" "}
          <Link to={`/datasets/${ds.id}/compare`} className="link">
            Compare two versions
          </Link>
          .
        </p>
      )}
      <UploadVersionDialog ds={ds} open={uploadOpen} onClose={() => setUploadOpen(false)} />
      <Dialog
        open={!!promote}
        onClose={() => setPromote(null)}
        size="sm"
        title={`Make v${promote?.version_number} active?`}
        description="Consumers will read this version. This is a manual override and is recorded in the audit log with your note."
        footer={
          <>
            <Button variant="ghost" onClick={() => setPromote(null)}>
              Cancel
            </Button>
            <Button variant="primary" disabled={note.trim().length < 3} loading={doPromote.isPending} onClick={() => doPromote.mutate()}>
              Make active
            </Button>
          </>
        }
      >
        {promote?.status === "quarantined" && (
          <Callout tone="warn" className="mb-3">
            This version is quarantined because monitoring found problems. Promoting it does not resolve the incident.
          </Callout>
        )}
        <Field label="Reason" htmlFor="promote_note" hint="At least 3 characters">
          <Textarea id="promote_note" value={note} onChange={(e) => setNote(e.target.value)} rows={3} data-autofocus />
        </Field>
      </Dialog>
    </>
  );
}
