import { Children, cloneElement, isValidElement, type ReactElement } from "react";

type FormFieldProps = {
  label: string;
  htmlFor: string;
  description?: string;
  error?: string | null;
  children: React.ReactNode;
};

type ControlProps = { id?: string; "aria-describedby"?: string; "aria-invalid"?: boolean };

/**
 * A labelled control. The label names the control and nothing else; the
 * description and any error are tied to it with `aria-describedby`, so a
 * screen reader says "Name" and then the hint, rather than reading the hint,
 * and every option of a select, as the field's name (A8: one wrapping
 * `<label>` did exactly that, on every form).
 */
export function FormField({ label, htmlFor, description, error, children }: FormFieldProps) {
  const only = Children.count(children) === 1 && isValidElement(children) ? (children as ReactElement<ControlProps>) : null;
  if (!only) {
    // Several children: the label wraps them, as before, so the first
    // control inside is still the one it names.
    return (
      <label htmlFor={htmlFor} className="block space-y-2">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium text-ink">{label}</span>
          {error ? <span className="text-xs text-danger">{error}</span> : null}
        </div>
        {description ? <p className="text-xs leading-5 text-ink-3">{description}</p> : null}
        {children}
      </label>
    );
  }

  const descriptionId = description ? `${htmlFor}-description` : undefined;
  const errorId = error ? `${htmlFor}-error` : undefined;
  const describedBy = [only.props["aria-describedby"], descriptionId, errorId].filter(Boolean).join(" ") || undefined;
  const control = cloneElement(only, {
    id: only.props.id ?? htmlFor,
    "aria-describedby": describedBy,
    ...(error ? { "aria-invalid": true } : {}),
  });

  return (
    <div className="block space-y-2">
      <div className="flex items-center justify-between gap-3">
        <label htmlFor={only.props.id ?? htmlFor} className="text-sm font-medium text-ink">
          {label}
        </label>
        {error ? (
          <span id={errorId} className="text-xs text-danger">
            {error}
          </span>
        ) : null}
      </div>
      {description ? (
        <p id={descriptionId} className="text-xs leading-5 text-ink-3">
          {description}
        </p>
      ) : null}
      {control}
    </div>
  );
}
