type FormFieldProps = {
  label: string;
  htmlFor: string;
  description?: string;
  error?: string | null;
  children: React.ReactNode;
};

export function FormField({ label, htmlFor, description, error, children }: FormFieldProps) {
  return (
    <label htmlFor={htmlFor} className="block space-y-2">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-slate-100">{label}</span>
        {error ? <span className="text-xs text-rose-300">{error}</span> : null}
      </div>
      {description ? <p className="text-xs leading-5 text-slate-400">{description}</p> : null}
      {children}
    </label>
  );
}
