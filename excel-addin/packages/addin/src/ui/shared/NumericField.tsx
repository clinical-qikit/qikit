import React from 'react';
import { Field, Input } from '@fluentui/react-components';

interface NumericFieldProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  min?: number;
  max?: number;
  integer?: boolean;
  id?: string;
  ariaLabel?: string;
}

/**
 * Returns a validation message for a numeric option string, or null when valid.
 * Parsing stays permissive (trims whitespace, empty means "unset"); only genuine
 * non-numbers and out-of-range values produce a message.
 */
export function validateNumeric(
  raw: string,
  opts: { min?: number; max?: number; integer?: boolean } = {},
): string | null {
  const trimmed = raw.trim();
  if (trimmed === '') return null;
  const n = Number(trimmed);
  if (isNaN(n)) return 'Enter a number';
  if (opts.integer && !Number.isInteger(n)) return 'Enter a whole number';
  if (opts.min !== undefined && n < opts.min) return `Must be at least ${opts.min}`;
  if (opts.max !== undefined && n > opts.max) return `Must be at most ${opts.max}`;
  return null;
}

/** Small numeric input that shows an inline validation message instead of silently coercing. */
export const NumericField: React.FC<NumericFieldProps> = ({
  value, onChange, placeholder, min, max, integer, id, ariaLabel,
}) => {
  const message = validateNumeric(value, { min, max, integer });
  return (
    <Field
      validationMessage={message ?? undefined}
      validationState={message ? 'error' : 'none'}
    >
      <Input
        size="small"
        id={id}
        aria-label={ariaLabel}
        placeholder={placeholder}
        value={value}
        onChange={(_, d) => onChange(d.value)}
      />
    </Field>
  );
};
