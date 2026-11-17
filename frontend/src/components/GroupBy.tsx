// One group-by / split control for every table (HANDOFF_V2 §11.4): a labelled
// radio group, keyboard-navigable like any native radio set.
import "./StatusTree.css";

export function GroupBy<T extends string>({
  options,
  value,
  onChange,
  name = "group-by",
  label = "Group by",
}: {
  options: readonly { key: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  name?: string;
  label?: string;
}) {
  return (
    <fieldset className="group-by" data-testid="group-by">
      <legend>{label}</legend>
      {options.map((o) => (
        <label key={o.key} className={value === o.key ? "group-by__opt group-by__opt--on" : "group-by__opt"}>
          <input type="radio" name={name} value={o.key} checked={value === o.key} onChange={() => onChange(o.key)} />
          {o.label}
        </label>
      ))}
    </fieldset>
  );
}
