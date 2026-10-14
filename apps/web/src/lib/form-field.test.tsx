import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { FormField, Input, Select } from "@platform/shared-ui";

/*
 * A field's label names its control and nothing else (A8). One wrapping
 * <label> made every hint, and every option of a select, part of the name a
 * screen reader announced.
 */
describe("a form field", () => {
  it("names its control with the label alone and describes it with the hint", () => {
    const html = renderToStaticMarkup(
      <FormField label="Address" htmlFor="address" description="Where events are sent." error="Not complete.">
        <Input id="address" />
      </FormField>,
    );
    expect(html).toContain('<label for="address" class="text-sm font-medium text-ink">Address</label>');
    expect(html).toContain('id="address-description"');
    expect(html).toMatch(/<input[^>]*aria-describedby="address-description address-error"/);
    expect(html).toMatch(/<input[^>]*aria-invalid="true"/);
    expect(html.indexOf("</label>")).toBeLessThan(html.indexOf("<input"));  // the label closes before the control
  });

  it("gives an unnamed control the field's id", () => {
    const html = renderToStaticMarkup(
      <FormField label="Send to" htmlFor="send-to">
        <Select>
          <option>Email</option>
        </Select>
      </FormField>,
    );
    expect(html).toMatch(/<select[^>]*id="send-to"/);
    expect(html.indexOf("</label>")).toBeLessThan(html.indexOf("<select"));
  });
});
