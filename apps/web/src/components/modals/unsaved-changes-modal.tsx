"use client";

import { Button } from "@platform/shared-ui";

import { Modal } from "@/components/ui/modal";

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
      description={message}
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
      <div className="rounded-2xl border border-warning-line bg-warning-soft px-4 py-4 text-sm leading-6 text-warning">
        Unsaved edits in this editor will be discarded if you continue.
      </div>
    </Modal>
  );
}
