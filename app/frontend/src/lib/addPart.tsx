/**
 * The Add A Part window's open/close state, lifted to one place so every entry
 * point opens the SAME modal: the Components toolbar button, the Ctrl+K palette,
 * and a vendor ZIP dropped anywhere in the window. It is a plain in-window modal
 * (no route, no OS window), so opening it never navigates away from wherever the
 * user is. AppShell renders <AddPartModal/> off this; consumers call open()/close().
 */
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

interface AddPartValue {
  isOpen: boolean;
  open: () => void;
  close: () => void;
}

const AddPartContext = createContext<AddPartValue | null>(null);

export function AddPartProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const value = useMemo<AddPartValue>(
    () => ({ isOpen, open: () => setIsOpen(true), close: () => setIsOpen(false) }),
    [isOpen],
  );
  return <AddPartContext.Provider value={value}>{children}</AddPartContext.Provider>;
}

export function useAddPart(): AddPartValue {
  const ctx = useContext(AddPartContext);
  if (!ctx) throw new Error("useAddPart must be used within an AddPartProvider");
  return ctx;
}
