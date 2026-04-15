import { createUnsavedChangesGuardController } from "@/features/navigation/unsaved-changes-guard-controller";

describe("unsaved changes guard controller", () => {
  it("registers and unregisters a dirty guard", () => {
    const controller = createUnsavedChangesGuardController();

    controller.registerGuard("pipeline", { when: true, title: "Leave?", message: "Unsaved edits." });
    expect(controller.getSnapshot().activeGuard).toMatchObject({
      id: "pipeline",
      title: "Leave?",
      message: "Unsaved edits.",
    });

    controller.unregisterGuard("pipeline");
    expect(controller.getSnapshot().activeGuard).toBeNull();
    expect(controller.getSnapshot().isModalOpen).toBe(false);
  });

  it("does not block navigation when clean", () => {
    const controller = createUnsavedChangesGuardController();
    const proceed = vi.fn();

    const blocked = controller.requestNavigation({
      kind: "link",
      proceed,
    });

    expect(blocked).toBe(false);
    expect(proceed).toHaveBeenCalledTimes(1);
    expect(controller.getSnapshot().isModalOpen).toBe(false);
  });

  it("opens the modal when navigating away while dirty", () => {
    const controller = createUnsavedChangesGuardController();

    controller.registerGuard("pipeline", { when: true });
    const blocked = controller.requestNavigation({
      kind: "link",
      proceed: vi.fn(),
    });

    expect(blocked).toBe(true);
    expect(controller.getSnapshot().isModalOpen).toBe(true);
    expect(controller.getSnapshot().pendingNavigation?.kind).toBe("link");
  });

  it("confirm leave proceeds and calls the confirm callback", () => {
    const controller = createUnsavedChangesGuardController();
    const proceed = vi.fn();
    const onConfirmLeave = vi.fn();

    controller.registerGuard("pipeline", { when: true, onConfirmLeave });
    controller.requestNavigation({
      kind: "programmatic",
      proceed,
    });
    controller.confirmNavigation();

    expect(onConfirmLeave).toHaveBeenCalledTimes(1);
    expect(proceed).toHaveBeenCalledTimes(1);
    expect(controller.getSnapshot().isModalOpen).toBe(false);
    expect(controller.getSnapshot().pendingNavigation).toBeNull();
  });

  it("cancel leave stays on the page and runs restore/cancel callbacks", () => {
    const controller = createUnsavedChangesGuardController();
    const proceed = vi.fn();
    const restore = vi.fn();
    const onCancelLeave = vi.fn();

    controller.registerGuard("pipeline", { when: true, onCancelLeave });
    controller.requestNavigation({
      kind: "history",
      proceed,
      restore,
    });
    controller.cancelNavigation();

    expect(onCancelLeave).toHaveBeenCalledTimes(1);
    expect(restore).toHaveBeenCalledTimes(1);
    expect(proceed).not.toHaveBeenCalled();
    expect(controller.getSnapshot().isModalOpen).toBe(false);
  });
});
