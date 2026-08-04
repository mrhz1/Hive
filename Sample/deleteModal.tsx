<div
      className="
    fixed inset-0 z-50 flex items-center justify-center p-4
    bg-[rgb(var(--background))/0.6]
    backdrop-blur-sm
  "
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
      aria-describedby="modal-description"
    >
      <div
        ref={modalRef}
        className="
      bg-[rgb(var(--surface))]
      rounded-xl shadow-xl
      max-w-md w-full p-6
      border border-[rgb(var(--border))]
    "
      >
        <h2 id="modal-title" className="text-lg font-bold text-[rgb(var(--foreground))]">
          Delete {title} Record
        </h2>

        <p id="modal-description" className="text-sm mt-2 text-[rgb(var(--foreground-muted))]">
          Are you sure you want to delete{" "}
          <span className="font-semibold text-[rgb(var(--foreground))]">{name}</span>? This
          action is permanent and cannot be undone.
        </p>

        <div className="flex justify-end gap-3 mt-6">
          <Button type="button" onClick={onClose} variant={"outline"}>
            Cancel
          </Button>

          <Button
            variant={"danger"}
            type="button"
            onClick={() => {
              onConfirm();
              onClose();
            }}
          >
            Confirm Delete
          </Button>
        </div>
      </div>
    </div>
