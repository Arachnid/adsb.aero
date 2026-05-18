import { test, expect } from "@playwright/test";
import { QueryBuilderPage } from "./helpers";

// ---- Fixtures ---------------------------------------------------------------

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  // Wait for map canvas to appear — signals the app has mounted
  await page.waitForSelector("canvas", { timeout: 10_000 });
});

// ---- Tests ------------------------------------------------------------------

test.describe("app shell", () => {
  test("loads with title and empty query builder", async ({ page }) => {
    await expect(page).toHaveTitle(/adsb\.aero/i);
    const qb = new QueryBuilderPage(page);
    await expect(qb.emptyState).toBeVisible();
    await expect(qb.runButton).toBeDisabled();
  });

  test("shows adsb.aero branding in the topbar", async ({ page }) => {
    await expect(page.getByText(/adsb\.aero/i).first()).toBeVisible();
  });

  test("left sidebar collapses and expands", async ({ page }) => {
    // Sidebar uses CSS transform to slide off-screen; check viewport intersection
    const sidebarTitle = page.getByText("Query Builder", { exact: true });
    await expect(sidebarTitle).toBeInViewport();

    await page.getByRole("button", { name: /collapse left panel/i }).click();
    await expect(sidebarTitle).not.toBeInViewport();

    await page.getByRole("button", { name: /expand left panel/i }).click();
    await expect(sidebarTitle).toBeInViewport();
  });
});

test.describe("callsign filter", () => {
  test("add filter enables run button once pattern is typed", async ({
    page,
  }) => {
    const qb = new QueryBuilderPage(page);

    await qb.addFilter("Callsign");
    // Filter appears but run button still disabled (empty pattern)
    await expect(page.locator(".pred--invalid")).toBeVisible();
    await expect(qb.runButton).toBeDisabled();

    await qb.typeCallsignPattern("^BAW");
    await expect(page.locator(".pred--invalid")).not.toBeVisible();
    await expect(qb.runButton).toBeEnabled();
  });

  test("removing the filter returns to empty state", async ({ page }) => {
    const qb = new QueryBuilderPage(page);

    await qb.addFilter("Callsign");
    await qb.typeCallsignPattern("^BAW");
    await expect(qb.runButton).toBeEnabled();

    await qb.removeFilter();
    await expect(qb.emptyState).toBeVisible();
    await expect(qb.runButton).toBeDisabled();
  });

  test("filter meta in sidebar header updates as filters are added", async ({
    page,
  }) => {
    await expect(page.getByText("no filters", { exact: true })).toBeVisible();

    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Callsign");
    await expect(page.getByText("1 filter", { exact: true })).toBeVisible();

    await qb.addFilter("Callsign");
    await expect(page.getByText("2 filters", { exact: true })).toBeVisible();
  });
});

test.describe("aircraft filter", () => {
  test("selecting an ICAO type enables run button", async ({ page }) => {
    const qb = new QueryBuilderPage(page);

    await qb.addFilter("Aircraft");
    await expect(qb.runButton).toBeDisabled();

    await qb.openChipDropdown(0); // ICAO type dropdown
    await qb.selectChipOption("B738");

    await expect(qb.runButton).toBeEnabled();
  });

  test("selected ICAO type appears as a chip", async ({ page }) => {
    const qb = new QueryBuilderPage(page);

    await qb.addFilter("Aircraft");
    await qb.openChipDropdown(0);
    await qb.selectChipOption("A320");

    await expect(page.locator(".chip").getByText("A320")).toBeVisible();
  });

  test("removing a chip disables run button again", async ({ page }) => {
    const qb = new QueryBuilderPage(page);

    await qb.addFilter("Aircraft");
    await qb.openChipDropdown(0);
    await qb.selectChipOption("B738");
    await expect(qb.runButton).toBeEnabled();

    // Click the × inside the chip
    await page.locator(".chip").getByRole("button", { name: "Remove" }).click();
    await expect(qb.runButton).toBeDisabled();
  });
});

test.describe("starts within filter", () => {
  test("shape=none with no time is invalid", async ({ page }) => {
    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Starts within");
    await expect(page.locator(".pred--invalid")).toBeVisible();
    await expect(qb.runButton).toBeDisabled();
  });

  test("shape=viewport is immediately valid", async ({ page }) => {
    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Starts within");
    await qb.clickShapeToggle("Viewport");
    await expect(page.locator(".pred--invalid")).not.toBeVisible();
    await expect(qb.runButton).toBeEnabled();
  });

  test("shape=none with a time window is valid", async ({ page }) => {
    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Starts within");

    // Fill the From datetime input (first datetime-local inside the starts-within card)
    const fromInput = page.locator('[type="datetime-local"]').first();
    await fromInput.fill("2024-06-01T00:00");

    await expect(page.locator(".pred--invalid")).not.toBeVisible();
    await expect(qb.runButton).toBeEnabled();
  });

  test("selecting circle shape reveals radius slider", async ({ page }) => {
    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Starts within");
    await qb.clickShapeToggle("Circle");
    await expect(page.getByText("Radius")).toBeVisible();
  });

  test("selecting polygon shape reveals draw button", async ({ page }) => {
    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Starts within");
    await qb.clickShapeToggle("Polygon");
    await expect(
      page.getByRole("button", { name: "Draw on map" }),
    ).toBeVisible();
  });
});

test.describe("within filter", () => {
  test("altitude inputs are hidden for shape=none", async ({ page }) => {
    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Within");
    await expect(page.getByText("Alt min (ft)")).not.toBeVisible();
  });

  test("altitude inputs appear when shape=viewport", async ({ page }) => {
    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Within");
    await qb.clickShapeToggle("Viewport");
    await expect(page.getByText("Alt min (ft)")).toBeVisible();
    await expect(qb.runButton).toBeEnabled();
  });
});

test.describe("multiple filters", () => {
  test("two valid filters both enable run button", async ({ page }) => {
    const qb = new QueryBuilderPage(page);

    await qb.addFilter("Callsign");
    await qb.typeCallsignPattern("^BAW");

    await qb.addFilter("Starts within");
    await qb.clickShapeToggle("Viewport");

    await expect(qb.runButton).toBeEnabled();
  });

  test("one invalid filter among valid ones disables run button", async ({
    page,
  }) => {
    const qb = new QueryBuilderPage(page);

    await qb.addFilter("Callsign");
    await qb.typeCallsignPattern("^BAW");

    await qb.addFilter("Callsign"); // second callsign — empty, invalid

    await expect(qb.runButton).toBeDisabled();
  });

  test("add group produces nested group block", async ({ page }) => {
    const qb = new QueryBuilderPage(page);
    await qb.addFilter("All of");
    await expect(page.locator(".filter-group")).toBeVisible();
  });
});
