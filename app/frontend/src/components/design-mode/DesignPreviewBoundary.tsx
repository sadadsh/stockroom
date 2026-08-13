import { Component, type ErrorInfo, type ReactNode } from "react";
import { useText } from "../../lib/copy";

interface DesignPreviewBoundaryProps {
  children: ReactNode;
  resetKey: string;
  onRecover: () => void;
}

interface RecoveryCopy {
  title: string;
  detail: string;
  action: string;
}

interface PreviewBoundaryProps extends DesignPreviewBoundaryProps {
  copy: RecoveryCopy;
}

interface DesignPreviewBoundaryState {
  error: Error | null;
}

/** Keeps Design Studio chrome operable even when one product subtree cannot render. */
class PreviewBoundary extends Component<
  PreviewBoundaryProps,
  DesignPreviewBoundaryState
> {
  state: DesignPreviewBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): DesignPreviewBoundaryState {
    return { error };
  }

  componentDidUpdate(previous: DesignPreviewBoundaryProps): void {
    if (this.state.error && previous.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Design Studio preview recovered from a render error.", error, info);
  }

  private recover = () => {
    this.props.onRecover();
  };

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="m-4 rounded-card border border-err/40 bg-err/10 p-4 text-sm text-t1">
        <p className="font-semibold">{this.props.copy.title}</p>
        <p className="mt-1 text-xs text-t2">{this.props.copy.detail}</p>
        <button
          type="button"
          onClick={this.recover}
          className="mt-3 rounded-control bg-acc px-3 py-1.5 text-xs font-semibold text-acc-on"
        >
          {this.props.copy.action}
        </button>
      </div>
    );
  }
}

export function DesignPreviewBoundary(props: DesignPreviewBoundaryProps) {
  const title = useText(
    "design-studio.preview-recovery.title",
    "Preview stopped before Stockroom could go blank.",
  );
  const detail = useText(
    "design-studio.preview-recovery.detail",
    "Undo the last design change, then continue editing.",
  );
  const action = useText(
    "design-studio.preview-recovery.action",
    "Undo Last Design Change",
  );
  return <PreviewBoundary {...props} copy={{ title, detail, action }} />;
}
