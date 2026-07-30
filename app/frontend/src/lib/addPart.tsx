/**
 * The Add A Part window's open/close state, lifted to one place so every entry
 * point opens the SAME modal: the Components toolbar button, the Ctrl+K palette,
 * from the Components toolbar and command palette. It is a plain in-window modal
 * (no route, no OS window), so opening it never navigates away from wherever the
 * user is. AppShell renders <AddPartModal/> off this; consumers call open()/close().
 */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { readUiSession, updateUiSession } from "./uiSession";

interface AddPartValue {
  isOpen: boolean;
  open: () => void;
  close: () => void;
}

const AddPartContext = createContext<AddPartValue | null>(null);

export function AddPartProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(
    () => readUiSession().open_surface === "add_part",
  );
  const open = useCallback(() => {
    setIsOpen(true);
    if (readUiSession().open_surface !== "add_part") {
      updateUiSession((current) => ({ ...current, open_surface: "add_part" }));
    }
  }, []);
  const close = useCallback(() => {
    setIsOpen(false);
    if (readUiSession().open_surface === "add_part") {
      updateUiSession((current) => ({ ...current, open_surface: null }));
    }
  }, []);
  const value = useMemo<AddPartValue>(
    () => ({ isOpen, open, close }),
    [close, isOpen, open],
  );
  return <AddPartContext.Provider value={value}>{children}</AddPartContext.Provider>;
}

export function useAddPart(): AddPartValue {
  const ctx = useContext(AddPartContext);
  if (!ctx) throw new Error("useAddPart must be used within an AddPartProvider");
  return ctx;
}
