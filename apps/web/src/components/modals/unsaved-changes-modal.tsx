"use client";

import { Button, Modal } from "@platform/shared-ui";

type UnsavedChangesModalProps = {
  open: boolean;
  title: string;
  message: string;
  onStay: () => void;
  onLeave: () => void;
};

export function UnsavedChangesModal({
  open,
  title,
  message,
  onStay,
  onLeave,
}: UnsavedChangesModalProps) {
  return (
    <Modal
      open={open}
      title={title}
      onClose={onStay}
      widthClassName="max-w-lg"
      footer={
        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onStay}>
            Stay on page
          </Button>
          <Button variant="danger" onClick={onLeave}>
            Leave without saving
          </Button>
        </div>
      }
    >
      <p className="text-sm leading-6 text-ink-2">{message}</p>
    </Modal>
  );
}
