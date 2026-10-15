import { test, expect } from "@playwright/test";

// Full user journey against a live stack (API at NEXT_PUBLIC_API_URL).
// Run: npx playwright test --project=chromium (needs `docker compose up`).
// E2E_NO_SERVER=1 skips the dev-server bootstrap when CI already serves web.
test("signup -> upload -> graph renders -> impact panel", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;
  await page.goto("/signup");
  await page.getByLabel(/organization|org/i).fill("E2E Co");
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill("Str0ng-Pass!9");
  await page.getByRole("button", { name: /create|sign up/i }).click();
  await expect(page).not.toHaveURL(/signup/, { timeout: 15_000 });

  await page.goto("/data");
  const csv = "supplier_id,name,capacity\nS1,Acme,5000\nS2,Globex,3200\n";
  await page.setInputFiles('input[type="file"]', {
    name: "suppliers.csv", mimeType: "text/csv", buffer: Buffer.from(csv),
  });
  await expect(page.getByText(/completed|supplier/i).first()).toBeVisible({ timeout: 30_000 });

  await page.goto("/workspace");
  await expect(page.getByRole("img", { name: /business graph/i })).toBeVisible({ timeout: 30_000 });
});
