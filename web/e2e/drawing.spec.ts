/**
 * E2E tests for polygon drawing and circle picking on the map.
 *
 * The map callout label (rendered by MapLibre as a symbol layer) and the
 * filter card header (.pred-name) are both derived from the same
 * collectGeometries → label pipeline, so asserting the card header text is
 * asserting what the callout will show.
 *
 * "Visible on the map" is verified by comparing canvas pixel buffers before
 * and after drawing — a shape appearing on a WebGL canvas changes the pixels.
 *
 * Requires the dev stack: make dev  (docker compose up with the vite service).
 */

import { test, expect, type Page } from "@playwright/test";
import {
  QueryBuilderPage,
  MAP_X,
  MAP_Y_MID,
} from "./helpers";

// ---- Map interaction helpers ------------------------------------------------

/** Clicks a point on the map canvas. x/y are within the safe map area (right of sidebar). */
async function mapClick(page: Page, x: number, y: number): Promise<void> {
  await page.locator("canvas").click({ position: { x, y } });
}

/** Double-clicks on the map canvas to finish polygon drawing. */
async function mapDblClick(page: Page, x: number, y: number): Promise<void> {
  await page.locator("canvas").dblclick({ position: { x, y } });
}

/**
 * Reads all pixels from the MapLibre WebGL canvas via Playwright's screenshot
 * API and returns a Buffer. Used to verify that shapes appear on the map.
 */
async function canvasSnapshot(page: Page): Promise<Buffer> {
  return page.locator("canvas").screenshot();
}

// ---- Polygon drawing --------------------------------------------------------

test.describe("polygon drawing", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("canvas", { timeout: 10_000 });
    // Let the map initialise and tile requests settle
    await page.waitForTimeout(800);
  });

  test("three clicks then double-click completes the polygon", async ({ page }) => {
    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Starts within");
    await qb.clickShapeToggle("Polygon");
    await page.getByRole("button", { name: "Draw on map" }).click();

    // Armed: button text changes
    await expect(page.getByText("Drawing… (dbl-click to finish)")).toBeVisible();

    // Draw a triangle (all coords in safe map area, clear of the sidebar)
    await mapClick(page, MAP_X, 220);
    await mapClick(page, MAP_X + 200, 220);
    await mapClick(page, MAP_X + 100, 420);

    // Finish with a double-click (adds one more point then fires dblclick handler)
    await mapDblClick(page, MAP_X + 100, 320);

    // Polygon summary replaces "No polygon defined"
    await expect(page.getByText(/◆ Polygon \d+ pts/)).toBeVisible();
    // Button reverts to Redraw
    await expect(page.getByRole("button", { name: "Redraw" })).toBeVisible();
  });

  test("completing a polygon enables the run button", async ({ page }) => {
    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Starts within");
    await qb.clickShapeToggle("Polygon");
    await page.getByRole("button", { name: "Draw on map" }).click();

    await mapClick(page, MAP_X, 220);
    await mapClick(page, MAP_X + 200, 220);
    await mapClick(page, MAP_X + 100, 420);
    await mapDblClick(page, MAP_X + 100, 320);

    await expect(qb.runButton).toBeEnabled();
  });

  test("filter card label is 'Starts Within 1' after drawing", async ({ page }) => {
    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Starts within");
    await qb.clickShapeToggle("Polygon");
    await page.getByRole("button", { name: "Draw on map" }).click();

    await mapClick(page, MAP_X, 220);
    await mapClick(page, MAP_X + 200, 220);
    await mapClick(page, MAP_X + 100, 420);
    await mapDblClick(page, MAP_X + 100, 320);

    // .pred-name is exactly what MapLibre renders as the callout label
    await expect(page.locator(".pred-name").first()).toHaveText("Starts Within 1");
  });

  test("two polygon filters get independent sequential labels", async ({ page }) => {
    const qb = new QueryBuilderPage(page);

    // First polygon: starts_within
    await qb.addFilter("Starts within");
    await qb.clickShapeToggle("Polygon");
    await page.getByRole("button", { name: "Draw on map" }).click();
    await mapClick(page, MAP_X, 200);
    await mapClick(page, MAP_X + 150, 200);
    await mapClick(page, MAP_X + 75, 380);
    await mapDblClick(page, MAP_X + 75, 290);
    await expect(page.getByText(/◆ Polygon \d+ pts/).first()).toBeVisible();

    // Second polygon: ends_within (different base label)
    await qb.addFilter("Ends within");
    // Two predicate cards now — scope the shape toggle to the new (last) card
    await page.locator(".pred").last().getByRole("button", { name: "Polygon" }).click();
    await page.locator(".pred").last().getByRole("button", { name: "Draw on map" }).click();
    await mapClick(page, MAP_X + 300, 200);
    await mapClick(page, MAP_X + 450, 200);
    await mapClick(page, MAP_X + 375, 380);
    await mapDblClick(page, MAP_X + 375, 290);
    await expect(page.getByText(/◆ Polygon \d+ pts/).nth(1)).toBeVisible();

    // Labels are independent — each series starts at 1
    await expect(page.getByText("Starts Within 1", { exact: true })).toBeVisible();
    await expect(page.getByText("Ends Within 1", { exact: true })).toBeVisible();
  });

  test("two polygon filters of the same kind get incrementing numbers", async ({ page }) => {
    const qb = new QueryBuilderPage(page);

    async function drawPoly(xOffset: number): Promise<void> {
      // Target the last card's Draw on map button (avoids Redraw vs Draw ambiguity)
      await page.locator(".pred").last().getByRole("button", { name: "Draw on map" }).click();
      await mapClick(page, MAP_X + xOffset, 200);
      await mapClick(page, MAP_X + xOffset + 130, 200);
      await mapClick(page, MAP_X + xOffset + 65, 360);
      await mapDblClick(page, MAP_X + xOffset + 65, 280);
    }

    await qb.addFilter("Starts within");
    await qb.clickShapeToggle("Polygon");
    await drawPoly(0);
    await expect(page.getByText(/◆ Polygon \d+ pts/).first()).toBeVisible();

    await qb.addFilter("Starts within");
    await page.locator(".pred").last().getByRole("button", { name: "Polygon" }).click();
    await drawPoly(200);
    await expect(page.getByText(/◆ Polygon \d+ pts/).nth(1)).toBeVisible();

    await expect(page.locator(".pred-name").nth(0)).toHaveText("Starts Within 1");
    await expect(page.locator(".pred-name").nth(1)).toHaveText("Starts Within 2");
  });

  test("drawn polygon changes the map canvas pixels", async ({ page }) => {
    const before = await canvasSnapshot(page);

    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Starts within");
    await qb.clickShapeToggle("Polygon");
    await page.getByRole("button", { name: "Draw on map" }).click();

    await mapClick(page, MAP_X, 220);
    await mapClick(page, MAP_X + 250, 220);
    await mapClick(page, MAP_X + 125, 450);
    await mapDblClick(page, MAP_X + 125, 335);

    // Wait for MapLibre to flush the GeoJSON source update and re-render
    await expect(page.getByText(/◆ Polygon \d+ pts/)).toBeVisible();
    await page.waitForTimeout(300);

    const after = await canvasSnapshot(page);
    expect(before).not.toEqual(after);
  });
});

// ---- Circle picking ---------------------------------------------------------

test.describe("circle picking", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector("canvas", { timeout: 10_000 });
    await page.waitForTimeout(800);
  });

  test("picking a point shows coordinates and enables the run button", async ({ page }) => {
    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Starts within");
    await qb.clickShapeToggle("Circle");

    await page.getByRole("button", { name: "Pick on map" }).click();
    // Armed state
    await expect(page.getByText("Click on map…")).toBeVisible();

    // Click the map
    await mapClick(page, MAP_X + 100, MAP_Y_MID);

    // Armed state clears; coordinates replace "No point selected"
    await expect(page.getByText("Click on map…")).not.toBeVisible();
    await expect(page.getByText("No point selected")).not.toBeVisible();
    await expect(page.getByText(/\d+\.\d+°N/)).toBeVisible();
    await expect(qb.runButton).toBeEnabled();
  });

  test("filter card label is 'Starts Within 1' after picking", async ({ page }) => {
    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Starts within");
    await qb.clickShapeToggle("Circle");
    await page.getByRole("button", { name: "Pick on map" }).click();
    await mapClick(page, MAP_X + 100, MAP_Y_MID);

    await expect(qb.runButton).toBeEnabled();
    await expect(page.locator(".pred-name").first()).toHaveText("Starts Within 1");
  });

  test("picked circle changes the map canvas pixels", async ({ page }) => {
    const before = await canvasSnapshot(page);

    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Starts within");
    await qb.clickShapeToggle("Circle");
    await page.getByRole("button", { name: "Pick on map" }).click();
    await mapClick(page, MAP_X + 100, MAP_Y_MID);

    await expect(qb.runButton).toBeEnabled();
    await page.waitForTimeout(300);

    const after = await canvasSnapshot(page);
    expect(before).not.toEqual(after);
  });

  test("radius slider changes the circle radius shown in the card", async ({ page }) => {
    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Starts within");
    await qb.clickShapeToggle("Circle");
    await page.getByRole("button", { name: "Pick on map" }).click();
    await mapClick(page, MAP_X + 100, MAP_Y_MID);

    // Default radius is 25 nm
    await expect(page.getByText("25 nm")).toBeVisible();

    // Move slider to 50
    const slider = page.getByRole("slider");
    await slider.fill("50");
    await expect(page.getByText("50 nm")).toBeVisible();
  });

  test("picking a circle center and changing radius still keeps run enabled", async ({ page }) => {
    const qb = new QueryBuilderPage(page);
    await qb.addFilter("Starts within");
    await qb.clickShapeToggle("Circle");
    await page.getByRole("button", { name: "Pick on map" }).click();
    await mapClick(page, MAP_X + 100, MAP_Y_MID);

    await page.getByRole("slider").fill("75");
    await expect(qb.runButton).toBeEnabled();
  });
});
