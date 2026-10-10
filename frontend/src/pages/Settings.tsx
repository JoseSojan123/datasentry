import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus, UserPlus } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { CodeBlock } from "@/components/common/Json";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Callout, EmptyState, Field, Input, KV, LoadingBlock, Panel, Select, Switch, Tabs } from "@/components/ui/primitives";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError, del, get, patch, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtRelative } from "@/lib/format";
import { useTheme, type ThemePref } from "@/lib/theme";
import type { Role, User } from "@/lib/types";

interface ApiKey {
  id: number;
  name: string;
  prefix: string;
  role: Role;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  active: boolean;
}

function Preferences() {
  const { user, refresh } = useAuth();
  const { pref, setPref, reducedMotion, setReducedMotion } = useTheme();
  const p = (user?.preferences ?? {}) as Record<string, any>;
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => patch("/auth/me/preferences", body),
    onSuccess: () => {
      void refresh();
      toast.success("Preferences saved.");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not save."),
  });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel title="Appearance">
        <div className="space-y-4">
          <Field label="Theme" htmlFor="pref_theme">
            <Select
              id="pref_theme"
              value={pref}
              onChange={(e) => {
                setPref(e.target.value as ThemePref);
                save.mutate({ theme: e.target.value });
              }}
            >
              <option value="dark">Dark</option>
              <option value="light">Light</option>
              <option value="system">Match system</option>
            </Select>
          </Field>
          <div className="flex items-center justify-between gap-4 rounded border border-line px-3 py-2.5">
            <div>
              <label htmlFor="pref_motion" className="text-base">
                Reduce motion
              </label>
              <p className="text-sm text-muted">Turns off graph propagation, chart and page animations. Follows your system setting unless set here.</p>
            </div>
            <Switch
              id="pref_motion"
              label="Reduce motion"
              checked={reducedMotion}
              onChange={(v) => {
                setReducedMotion(v);
                save.mutate({ reduced_motion: v });
              }}
            />
          </div>
        </div>
      </Panel>
      <Panel title="Notifications" description="The bell shows notifications at or above the severity you choose. Email is sent only if this deployment has SMTP configured.">
        <div className="space-y-4">
          <Field label="In-app minimum severity" htmlFor="pref_inapp">
            <Select id="pref_inapp" value={p.in_app_min_severity ?? "info"} onChange={(e) => save.mutate({ in_app_min_severity: e.target.value })}>
              <option value="info">Info and above</option>
              <option value="warning">Warning and above</option>
              <option value="critical">Critical only</option>
            </Select>
          </Field>
          <div className="flex items-center justify-between gap-4 rounded border border-line px-3 py-2.5">
            <label htmlFor="pref_email" className="text-base">
              Email notifications
            </label>
            <Switch id="pref_email" label="Email notifications" checked={!!p.email_notifications} onChange={(v) => save.mutate({ email_notifications: v })} />
          </div>
          {p.email_notifications && (
            <Field label="Email minimum severity" htmlFor="pref_email_sev">
              <Select id="pref_email_sev" value={p.email_min_severity ?? "critical"} onChange={(e) => save.mutate({ email_min_severity: e.target.value })}>
                <option value="warning">Warning and above</option>
                <option value="critical">Critical only</option>
              </Select>
            </Field>
          )}
        </div>
      </Panel>
    </div>
  );
}

function Users() {
  const qc = useQueryClient();
  const { can, user: me } = useAuth();
  const q = useQuery({ queryKey: ["users"], queryFn: () => get<{ items: (User & { last_login_at: string | null })[] }>("/users") });
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ email: "", display_name: "", password: "", role: "viewer" });
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => post("/users", f),
    onSuccess: () => {
      toast.success("User added. Share the password with them through a secure channel.");
      setOpen(false);
      setF({ email: "", display_name: "", password: "", role: "viewer" });
      void qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not add the user."),
  });
  const role = useMutation({
    mutationFn: ({ id, r }: { id: number; r: string }) => patch(`/users/${id}/role`, { role: r }),
    onSuccess: () => {
      toast.success("Role updated.");
      void qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not change the role."),
  });
  return (
    <>
      <Panel
        title="Members"
        description="Viewers can read everything. Editors can upload, change rules and run remediation. Admins also manage users, API keys and the remediation policy."
        actions={can("admin") && <Button size="sm" variant="primary" icon={<UserPlus className="h-3.5 w-3.5" />} onClick={() => setOpen(true)}>Add user</Button>}
        bodyClassName="p-0"
      >
        {!q.data ? (
          <div className="p-4">
            <LoadingBlock rows={3} />
          </div>
        ) : (
          <Table label="Workspace members">
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Email</Th>
                <Th>Role</Th>
                <Th>Last sign-in</Th>
              </tr>
            </thead>
            <tbody>
              {q.data.items.map((u) => (
                <Tr key={u.id}>
                  <Td className="font-medium">
                    {u.display_name} {u.id === me?.id && <Badge className="ml-1">you</Badge>}
                  </Td>
                  <Td className="text-sm text-muted">{u.email}</Td>
                  <Td>
                    {can("admin") && u.id !== me?.id ? (
                      <Select aria-label={`Role of ${u.display_name}`} value={u.role} onChange={(e) => role.mutate({ id: u.id, r: e.target.value })} className="w-28">
                        <option value="viewer">Viewer</option>
                        <option value="editor">Editor</option>
                        <option value="admin">Admin</option>
                      </Select>
                    ) : (
                      <Badge tone={u.role === "admin" ? "accent" : "neutral"}>{u.role}</Badge>
                    )}
                  </Td>
                  <Td className="text-sm text-muted">{u.last_login_at ? fmtRelative(u.last_login_at) : "never"}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Panel>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Add a user"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" loading={create.isPending} disabled={!f.email || !f.display_name || f.password.length < 10} onClick={() => create.mutate()}>
              Add user
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          {error && <Callout tone="crit" className="sm:col-span-2">{error}</Callout>}
          <Field label="Name" htmlFor="u_name">
            <Input id="u_name" value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} data-autofocus />
          </Field>
          <Field label="Email" htmlFor="u_email">
            <Input id="u_email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
          </Field>
          <Field label="Initial password" htmlFor="u_pw" hint="At least 10 characters">
            <Input id="u_pw" type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
          </Field>
          <Field label="Role" htmlFor="u_role">
            <Select id="u_role" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
              <option value="viewer">Viewer</option>
              <option value="editor">Editor</option>
              <option value="admin">Admin</option>
            </Select>
          </Field>
        </div>
      </Dialog>
    </>
  );
}

function ApiKeys() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["api-keys"], queryFn: () => get<{ items: ApiKey[] }>("/api-keys") });
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", role: "editor", expires_in_days: "90" });
  const [secret, setSecret] = useState<string | null>(null);
  const [revoke, setRevoke] = useState<ApiKey | null>(null);
  const create = useMutation({
    mutationFn: () => post<ApiKey & { secret: string }>("/api-keys", { name: f.name.trim(), role: f.role, expires_in_days: f.expires_in_days ? Number(f.expires_in_days) : null }),
    onSuccess: (k) => {
      setSecret(k.secret);
      void qc.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not create the key."),
  });
  const doRevoke = useMutation({
    mutationFn: (k: ApiKey) => del(`/api-keys/${k.id}`),
    onSuccess: () => {
      toast.success("Key revoked. Requests using it now fail.");
      setRevoke(null);
      void qc.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not revoke."),
  });
  const close = () => {
    setOpen(false);
    setSecret(null);
    setF({ name: "", role: "editor", expires_in_days: "90" });
  };
  return (
    <>
      <Panel title="API keys" description="For the SDK and automation. Keys are stored as a keyed hash; the secret is shown once at creation." actions={<Button size="sm" variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setOpen(true)}>Create key</Button>} bodyClassName="p-0">
        {!q.data ? (
          <div className="p-4">
            <LoadingBlock rows={3} />
          </div>
        ) : q.data.items.length === 0 ? (
          <EmptyState icon={<KeyRound className="h-5 w-5" />} title="No API keys" />
        ) : (
          <Table label="API keys">
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Key</Th>
                <Th>Role</Th>
                <Th>Last used</Th>
                <Th>Expires</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {q.data.items.map((k) => (
                <Tr key={k.id} className={k.revoked_at ? "opacity-60" : undefined}>
                  <Td className="font-medium">{k.name}</Td>
                  <Td mono className="text-muted">
                    {k.prefix}
                  </Td>
                  <Td>
                    <Badge>{k.role}</Badge>
                  </Td>
                  <Td className="text-sm text-muted">{k.last_used_at ? fmtRelative(k.last_used_at) : "never"}</Td>
                  <Td className="text-sm text-muted">{k.revoked_at ? <Badge tone="crit">revoked</Badge> : k.expires_at ? fmtDate(k.expires_at) : "never"}</Td>
                  <Td align="right">
                    {!k.revoked_at && (
                      <Button size="sm" variant="ghost" onClick={() => setRevoke(k)}>
                        Revoke
                      </Button>
                    )}
                  </Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Panel>
      <Dialog
        open={open}
        onClose={close}
        title={secret ? "Copy your API key" : "Create an API key"}
        footer={
          secret ? (
            <Button variant="primary" onClick={close}>
              I have stored it
            </Button>
          ) : (
            <>
              <Button variant="ghost" onClick={close}>
                Cancel
              </Button>
              <Button variant="primary" disabled={!f.name.trim()} loading={create.isPending} onClick={() => create.mutate()}>
                Create
              </Button>
            </>
          )
        }
      >
        {secret ? (
          <div className="space-y-3">
            <Callout tone="warn">This is the only time the secret is shown. Store it in a secret manager; never commit it to a repository.</Callout>
            <CodeBlock code={secret} />
            <CodeBlock language="shell" code={`export DATASENTRY_API_URL=${window.location.origin}\nexport DATASENTRY_API_KEY=${secret}`} />
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Name" htmlFor="k_name" className="sm:col-span-2" hint="Where it is used, e.g. “nightly ETL”">
              <Input id="k_name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} data-autofocus />
            </Field>
            <Field label="Role" htmlFor="k_role">
              <Select id="k_role" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
                <option value="viewer">Viewer (read only)</option>
                <option value="editor">Editor</option>
                <option value="admin">Admin</option>
              </Select>
            </Field>
            <Field label="Expires after" htmlFor="k_exp">
              <Select id="k_exp" value={f.expires_in_days} onChange={(e) => setF({ ...f, expires_in_days: e.target.value })}>
                <option value="30">30 days</option>
                <option value="90">90 days</option>
                <option value="365">1 year</option>
                <option value="">Never</option>
              </Select>
            </Field>
          </div>
        )}
      </Dialog>
      <Dialog
        open={!!revoke}
        onClose={() => setRevoke(null)}
        size="sm"
        title={`Revoke “${revoke?.name}”?`}
        description="Anything using this key will start receiving 401 errors immediately."
        footer={
          <>
            <Button variant="ghost" onClick={() => setRevoke(null)}>
              Cancel
            </Button>
            <Button variant="danger" loading={doRevoke.isPending} onClick={() => revoke && doRevoke.mutate(revoke)}>
              Revoke key
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">Revocation cannot be undone; create a new key if needed.</p>
      </Dialog>
    </>
  );
}

export default function Settings() {
  const { can, workspace, user } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as "preferences" | "members" | "keys" | "workspace") || "preferences";
  return (
    <>
      <PageHeader title="Settings" />
      <Tabs
        className="mb-5"
        value={tab}
        onChange={(t) => setParams({ tab: t }, { replace: true })}
        tabs={[
          { id: "preferences", label: "Preferences" },
          { id: "members", label: "Members" },
          ...(can("admin") ? [{ id: "keys" as const, label: "API keys" }] : []),
          { id: "workspace", label: "Workspace" },
        ]}
      />
      {tab === "preferences" && <Preferences />}
      {tab === "members" && <Users />}
      {tab === "keys" && can("admin") && <ApiKeys />}
      {tab === "workspace" && (
        <Panel title={workspace?.name}>
          <KV
            items={[
              ["Workspace ID", <span key="i" className="font-mono">{workspace?.id}</span>],
              ["Type", workspace?.is_demo ? "Demo (synthetic data, expires)" : "Standard"],
              ["Expires", workspace?.expires_at ? `${fmtDate(workspace.expires_at)} (${fmtRelative(workspace.expires_at)})` : "never"],
              ["Your role", user?.role],
            ]}
          />
          {workspace?.is_demo && <Callout tone="info" className="mt-4">Demo workspaces and everything in them are deleted by the maintenance job after they expire.</Callout>}
        </Panel>
      )}
    </>
  );
}
