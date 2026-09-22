import { assessPassword } from "@/lib/password-strength";

describe("assessPassword", () => {
  it("rates an empty password as the weakest", () => {
    expect(assessPassword("").score).toBe(0);
    expect(assessPassword("").label).toBe("Too weak");
  });

  it("rewards length and variety", () => {
    expect(assessPassword("abc").score).toBeLessThan(
      assessPassword("Abcd3fgh!jkl").score,
    );
    expect(assessPassword("Tr0ub4dour&3xplosion").label).toBe("Strong");
  });

  it("does not let a common password read as strong", () => {
    expect(assessPassword("Password1").score).toBeLessThanOrEqual(2);
    expect(assessPassword("password").score).toBe(0);
    expect(assessPassword("pipewright").score).toBe(0);
  });

  it("punishes a single repeated character however long", () => {
    expect(assessPassword("aaaaaaaaaaaaaaaa").score).toBeLessThanOrEqual(1);
  });

  it("climbs monotonically as a password improves", () => {
    const scores = [
      assessPassword("abcdefgh").score,
      assessPassword("abcdEfgh").score,
      assessPassword("abcdEfg1").score,
      assessPassword("abcdEfg1!more").score,
    ];
    for (let i = 1; i < scores.length; i += 1) {
      expect(scores[i]).toBeGreaterThanOrEqual(scores[i - 1]);
    }
  });
});
