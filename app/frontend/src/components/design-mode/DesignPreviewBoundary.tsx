import { Component, type ErrorInfo, type ReactNode } from "react";
import { useText } from "../../lib/copy";

interface DesignPreviewBoundaryProps {
  children: ReactNode;
  resetKey: string;
  onRecover: () => void | Promise<void>;
  onRenderSuccess?: () => void;
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
  recovering: boolean;
}

/** Keeps Design Studio chrome operable even when one product subtree cannot render. */
class PreviewBoundary extends Component<
  PreviewBoundaryProps,
  DesignPreviewBoundaryState
> {
  state: DesignPreviewBoundaryState = { error: null, recovering: false };

  static getDerivedStateFromError(error: Error): DesignPreviewBoundaryState {
    return { error, recovering: false };
  }

  componentDidMount(): void {
    if (!this.state.error) this.props.onRenderSuccess?.();
  }

  componentDidUpdate(previous: DesignPreviewBoundaryProps): void {
    if (this.state.error && previous.resetKey !== this.props.resetKey) {
      this.setState({ error: null, recovering: false });
      return;
    }
    if (!this.state.error) this.props.onRenderSuccess?.();
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Design Studio preview recovered from a render error.", error, info);
  }

  private recover = () => {
    if (this.state.recovering) return;
    this.setState({ recovering: true });
    try {
      const recovery = this.props.onRecover();
      if (recovery instanceof Promise) {
        void recovery.then(
          () => this.setState({ error: null, recovering: false }),
          () => this.setState({ recovering: false }),
        );
        return;
      }
      // Undo may legitimately be empty (for example, the first render failed before any edit).
      // Clearing the boundary remounts only after recovery has restored renderable state.
      this.setState({ error: null, recovering: false });
    } catch {
      this.setState({ recovering: false });
    }
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
          disabled={this.state.recovering}
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
    "Recover the product preview, then continue editing.",
  );
  const action = useText(
    "design-studio.preview-recovery.action",
    "Recover Preview",
  );
  return <PreviewBoundary {...props} copy={{ title, detail, action }} />;
}
