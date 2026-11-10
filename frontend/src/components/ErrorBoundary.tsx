import { TriangleAlert } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "./ui";

/** Keeps a crash in one page from leaving the whole app blank. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Page crashed", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" className="mx-auto mt-16 max-w-md rounded-2xl border border-line bg-surface p-7 text-center shadow-card">
        <span className="mx-auto mb-3 flex size-10 items-center justify-center rounded-full bg-clay-soft text-clay">
          <TriangleAlert className="size-5" />
        </span>
        <h1 className="font-serif text-2xl font-medium">This page hit a problem</h1>
        <p className="mt-1.5 mb-5 text-sm leading-relaxed text-ink-2">
          Your data is safe. Reload the page. If it keeps happening after an update, restart the backend.
        </p>
        <Button variant="primary" onClick={() => window.location.reload()}>Reload</Button>
      </div>
    );
  }
}
