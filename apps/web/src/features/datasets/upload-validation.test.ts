import { formatBytes, validateDatasetUploadFile } from "@/features/datasets/upload-validation";

const maxUploadSizeBytes = 5 * 1024 * 1024;

function buildFile(name: string, size: number) {
  return new File([new Uint8Array(size)], name, { type: "application/octet-stream" });
}

describe("dataset upload validation", () => {
  it("rejects unsupported extensions", () => {
    expect(validateDatasetUploadFile(buildFile("notes.txt", 128), maxUploadSizeBytes)).toBe(
      "Unsupported file type. Upload csv, xlsx, or json files.",
    );
  });

  it("rejects empty uploads", () => {
    expect(validateDatasetUploadFile(buildFile("orders.csv", 0), maxUploadSizeBytes)).toBe(
      "Uploaded file is empty.",
    );
  });

  it("rejects oversize uploads", () => {
    expect(
      validateDatasetUploadFile(buildFile("orders.csv", maxUploadSizeBytes + 1), maxUploadSizeBytes),
    ).toBe("File exceeds the maximum size of 5 MB.");
  });

  it("accepts supported uploads within size limits", () => {
    expect(validateDatasetUploadFile(buildFile("orders.json", 256), maxUploadSizeBytes)).toBeNull();
  });

  it("formats upload sizes for UI notes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5 MB");
  });
});
