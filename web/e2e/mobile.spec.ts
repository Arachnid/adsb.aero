import { test, expect } from "@playwright/test";
import { QueryBuilderPage } from "./helpers";

// Enable touch and a mobile viewport so touchscreen.tap() works.
// 390×844 is the breakpoint our useMobile() hook uses (<= 639px).
test.use({
  hasTouch: true,
  viewport: { width: 390, height: 844 },
});

const MOCK_FLIGHT = {
  flight_id: "aabbcc:2024-01-01T10:00:00Z",
  icao24: "aabbcc",
  callsign: "TEST01",
  icao_type: "B738",
  emitter_category: "A3",
  registration: null,
  model: null,
  year: null,
  operator: null,
  start_ts: "2024-01-01T10:00:00Z",
  end_ts: "2024-01-01T12:00:00Z",
  start_point: { type: "Point", coordinates: [-10, 30, 35000] },
  end_point: { type: "Point", coordinates: [10, 30, 35000] },
  point_count: 3,
  path: {
    type: "MultiLineString",
    coordinates: [
      [
        [-10, 30, 35000],
        [0, 30, 35000],
        [10, 30, 35000],
      ],
    ],
  },
  timestamps: [[1704103200, 1704106800, 1704110400]],
};

const MOCK_QUERY_RESPONSE = {
  flights: [MOCK_FLIGHT],
  cursor: null,
  window_from: "2024-01-01T00:00:00Z",
};

test.describe("mobile sidebar behaviour", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/data-range", (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          first_date: "2022-01-01",
          last_date: "2024-12-31",
        }),
      }),
    );

    await page.route("**/api/v1/query", (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(MOCK_QUERY_RESPONSE),
      }),
    );

    await page.goto("/");
    await page.waitForSelector("canvas", { timeout: 10_000 });
  });

  test("left panel starts expanded on mobile", async ({ page }) => {
    const sidebarTitle = page.getByText("Query Builder", { exact: true });
    await expect(sidebarTitle).toBeInViewport();
  });

  test("tapping a flight trace does not re-open the collapsed right panel", async ({
    page,
  }) => {
    const qb = new QueryBuilderPage(page);
    await expect(qb.runButton).toBeEnabled({ timeout: 5_000 });

    // Run query → right panel opens, left panel collapses on mobile
    await qb.runButton.click();
    await expect(page.getByText("TEST01")).toBeVisible({ timeout: 5_000 });

    // Collapse the right panel
    await page.getByRole("button", { name: /collapse right panel/i }).click();
    await expect(page.getByText("TEST01")).not.toBeInViewport();
    await page.waitForTimeout(300);

    // Tap the flight trace. The mock flight runs along lat 30 which maps to
    // the vertical centre of the 390×844 viewport when the map starts at
    // centre [0, 30] zoom 2.
    await page.touchscreen.tap(195, 422);
    await page.waitForTimeout(300);

    // Right panel must stay collapsed — tapping the trace must not open it.
    await expect(page.getByText("TEST01")).not.toBeInViewport({
      timeout: 1_000,
    });
  });
});
