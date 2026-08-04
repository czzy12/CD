import type { LucideIcon } from "lucide-react";

export function IconButton({ icon: Icon, label, onClick, disabled = false }: { icon: LucideIcon; label: string; onClick?: () => void; disabled?: boolean }) {
  return <button className="icon-button" data-tooltip={label} aria-label={label} onClick={onClick} disabled={disabled}><Icon /></button>;
}
