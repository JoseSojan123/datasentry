import { zodResolver } from "@hookform/resolvers/zod";
import { Waves } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";
import { Logo } from "@/components/layout/Logo";
import { Button } from "@/components/ui/Button";
import { Callout, Field, Input } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useDocumentTitle } from "@/lib/hooks";

const loginSchema = z.object({
  email: z.string().email("Enter a valid email address."),
  password: z.string().min(1, "Enter your password."),
});
const registerSchema = z.object({
  display_name: z.string().trim().min(1, "Enter your name.").max(120),
  email: z.string().email("Enter a valid email address."),
  password: z.string().min(10, "Use at least 10 characters.").max(128),
  workspace_name: z.string().trim().min(1, "Name your workspace.").max(120),
});

type LoginValues = z.infer<typeof loginSchema>;
type RegisterValues = z.infer<typeof registerSchema>;

function safeNext(next: string | null) {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/overview";
}

export default function Auth({ mode }: { mode: "login" | "register" }) {
  useDocumentTitle(mode === "login" ? "Sign in" : "Create account");
  const { login, register: doRegister, startDemo } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [demoBusy, setDemoBusy] = useState(false);
  const isLogin = mode === "login";

  const form = useForm<LoginValues & Partial<RegisterValues>>({
    resolver: zodResolver(isLogin ? loginSchema : registerSchema) as any,
    defaultValues: { email: "", password: "", display_name: "", workspace_name: "My workspace" },
  });
  const { errors, isSubmitting } = form.formState;

  const onSubmit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      if (isLogin) await login(v.email, v.password);
      else await doRegister({ email: v.email, password: v.password, display_name: v.display_name!, workspace_name: v.workspace_name });
      navigate(safeNext(params.get("next")), { replace: true });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
    }
  });

  return (
    <div className="flex min-h-screen flex-col bg-bg">
      <div className="pointer-events-none fixed inset-0 grid-bg opacity-60 [mask-image:radial-gradient(ellipse_at_center,black_10%,transparent_65%)]" aria-hidden />
      <header className="relative px-4 py-5 sm:px-6">
        <Link to="/" aria-label="DataSentry home">
          <Logo />
        </Link>
      </header>
      <main className="relative flex flex-1 items-start justify-center px-4 pb-16 pt-6 sm:items-center sm:pt-0">
        <div className="w-full max-w-sm">
          <h1 className="text-2xl font-semibold tracking-tight">{isLogin ? "Sign in" : "Create your workspace"}</h1>
          <p className="mt-1 text-base text-muted">{isLogin ? "Welcome back." : "You will be the admin of a new, empty workspace."}</p>
          <form onSubmit={onSubmit} noValidate className="panel mt-6 space-y-4 p-5">
            {error && (
              <Callout tone="crit" className="py-2">
                <span role="alert">{error}</span>
              </Callout>
            )}
            {!isLogin && (
              <Field label="Your name" htmlFor="display_name" error={errors.display_name?.message}>
                <Input id="display_name" autoComplete="name" aria-invalid={!!errors.display_name} {...form.register("display_name")} />
              </Field>
            )}
            <Field label="Email" htmlFor="email" error={errors.email?.message}>
              <Input id="email" type="email" autoComplete="email" aria-invalid={!!errors.email} {...form.register("email")} />
            </Field>
            <Field label="Password" htmlFor="password" error={errors.password?.message} hint={!isLogin ? "At least 10 characters." : undefined}>
              <Input id="password" type="password" autoComplete={isLogin ? "current-password" : "new-password"} aria-invalid={!!errors.password} {...form.register("password")} />
            </Field>
            {!isLogin && (
              <Field label="Workspace name" htmlFor="workspace_name" error={errors.workspace_name?.message}>
                <Input id="workspace_name" aria-invalid={!!errors.workspace_name} {...form.register("workspace_name")} />
              </Field>
            )}
            <Button type="submit" variant="primary" className="w-full" size="lg" loading={isSubmitting}>
              {isLogin ? "Sign in" : "Create account"}
            </Button>
          </form>
          <div className="mt-4 flex items-center gap-3 text-xs text-faint">
            <span className="h-px flex-1 bg-line" /> or <span className="h-px flex-1 bg-line" />
          </div>
          <Button
            className="mt-4 w-full"
            size="lg"
            loading={demoBusy}
            icon={<Waves className="h-4 w-4" />}
            onClick={async () => {
              setDemoBusy(true);
              setError(null);
              try {
                await startDemo(true);
                navigate("/overview", { replace: true });
              } catch (e) {
                setError(e instanceof ApiError ? e.message : "Could not start the demo.");
              } finally {
                setDemoBusy(false);
              }
            }}
          >
            Try a private demo workspace
          </Button>
          <p className="mt-6 text-center text-sm text-muted">
            {isLogin ? (
              <>
                No account?{" "}
                <Link to="/register" className="link">
                  Create one
                </Link>
              </>
            ) : (
              <>
                Already have an account?{" "}
                <Link to="/login" className="link">
                  Sign in
                </Link>
              </>
            )}
          </p>
        </div>
      </main>
    </div>
  );
}
