import { formatBytes, validateDatasetUploadFile } from "@/features/datasets/upload-validation";

const maxUploadSizeBytes = 5 * 1024 * 1024;

function buildFile(name: string, size: number) {
  return new File([new Uint8Array(size)], name, { type: "application/octet-stream" });
}

describe("dataset upload validation", () => {
  it("rejects an extension nothing can read, and says what can be read", () => {
    expect(validateDatasetUploadFile(buildFile("slides.pptx", 128), maxUploadSizeBytes)).toContain(
      ".pptx files are not supported",
    );
  });

  it("accepts the formats the readers actually handle", () => {
    // `.txt` is delimited text often enough that refusing it here meant the
    // sniffer never got the chance to notice it was tab-separated.
    for (const name of [
      "export.txt",
      "feed.dat",
      "book.xlsx",
      "events.jsonl",
      "orders.xml",
      "data.parquet",
      "dump.sql",
      "orders.csv.gz",
    ]) {
      expect(validateDatasetUploadFile(buildFile(name, 256), maxUploadSizeBytes)).toBeNull();
    }
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
