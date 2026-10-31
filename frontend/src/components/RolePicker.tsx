// The "dev-mode role picker" the scoping conversation agreed to
// (HANDOFF.md). Deliberately, visibly labeled as NOT real
// authentication — app/security/rbac.py checks a role the caller
// *claims*, with no login/session system behind it (Milestone 9's
// documented limitation, docs/OPEN_QUESTIONS.md). This component
// exists to exercise that claimed-role check, never to imply more
// rigor than exists.
import type { Role } from "../api/types";
import "./RolePicker.css";

const ROLES: Role[] = ["operator", "supervisor", "admin"];

export function RolePicker({
  name,
  role,
  onNameChange,
  onRoleChange,
}: {
  name: string;
  role: Role;
  onNameChange: (name: string) => void;
  onRoleChange: (role: Role) => void;
}) {
  return (
    <div className="role-picker">
      <div className="role-picker__warning">
        ⚠ Dev-mode only — not real authentication. Any name/role combination is
        accepted and sent to the API as-is; the backend checks the role you pick
        here, not who you actually are.
      </div>
      <label className="role-picker__field">
        <span>Acting as</span>
        <input
          type="text"
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          placeholder="your name"
        />
      </label>
      <label className="role-picker__field">
        <span>Role</span>
        <select value={role} onChange={(e) => onRoleChange(e.target.value as Role)}>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
