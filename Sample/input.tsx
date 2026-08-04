import * as React from 'react';
import { AlertCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { inputVariants } from './Input.styles';
import { type InputProps, type FormFieldProps } from './Input.types';

// 1. Primitive Input Component
const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, error, type = 'text', ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(inputVariants({ state: error ? 'error' : 'default' }), className)}
        ref={ref}
        {...props}
      />
    );
  },
);
Input.displayName = 'Input';

// 2. FormField Wrapper (Labels & Errors)
const FormField = ({ label, fieldState, children, id }: FormFieldProps) => {
  return (
    <div className='w-full space-y-2'>
      <label
        htmlFor={id}
        className='ml-0.5 block text-[11px] font-bold tracking-widest text-slate-600 uppercase'
      >
        {label}
      </label>

      {children}
      {fieldState?.error && (
        <div
          role='alert'
          className='animate-in fade-in slide-in-from-top-1 flex items-center gap-1.5 px-1 text-[11px] font-semibold text-rose-600'
        >
          <AlertCircle size={12} strokeWidth={2.5} />
          <span className='whitespace-pre-line'>{fieldState.error.message}</span>
        </div>
      )}
    </div>
  );
};

export { Input, FormField };
