/**
 * E2E tests for URL hash share-link behaviour.
 *
 * Requires the dev stack: make dev
 */

import { test, expect } from "@playwright/test";

test.use({
  permissions: ["clipboard-read", "clipboard-write"],
});

test.beforeEach(async ({ page }) => {
  page.on("console", (msg) => {
    if (msg.type() === "error") console.error("[browser]", msg.text());
  });
  page.on("pageerror", (err) => console.error("[pageerror]", err));

  await page.goto("/");
  await page.waitForSelector("canvas", { timeout: 10_000 });
});

// ── Diagnostics ──────────────────────────────────────────────────────────────

test("diagnostic: hash value after 1s", async ({ page }) => {
  await page.waitForTimeout(1000);
  const hash = await page.evaluate(() => window.location.hash);
  const url = await page.evaluate(() => window.location.href);
  console.log("href after 1s:", url);
  console.log("hash after 1s:", JSON.stringify(hash));
});

test("diagnostic: CompressionStream works in page", async ({ page }) => {
  // Use page.addScriptTag so we don't race with React's useEffect.
  const result = await page.evaluate(() => {
    return typeof CompressionStream !== "undefined" ? "available" : "MISSING";
  });
  console.log("CompressionStream:", result);
  expect(result).toBe("available");
});

test("diagnostic: manual encodeShareUrl call", async ({ page }) => {
  // Wait for the React app to mount.
  await page.waitForTimeout(500);

  const result = await page.evaluate(async () => {
    // Manually invoke the same logic encodeShareUrl uses.
    try {
      const cs = new CompressionStream("deflate-raw");
      const writer = cs.writable.getWriter();
      const bytes = new TextEncoder().encode(
        '{"v":3,"g":{"kind":"group","mode":"all","items":[]},"d":{"to":""}}',
      );
      // Write and read concurrently to avoid any back-pressure deadlock.
      const readAll = (async () => {
        const reader = cs.readable.getReader();
        const chunks: Uint8Array[] = [];
        let c = await reader.read();
        while (!c.done) {
          chunks.push(c.value);
          c = await reader.read();
        }
        return chunks;
      })();
      await writer.write(bytes);
      await writer.close();
      const chunks = await readAll;
      const totalLen = chunks.reduce((n, c) => n + c.length, 0);
      const out = new Uint8Array(totalLen);
      let off = 0;
      for (const c of chunks) {
        out.set(c, off);
        off += c.length;
      }
      let latin1 = "";
      out.forEach((b) => (latin1 += String.fromCharCode(b)));
      return { ok: true, hash: "#" + btoa(latin1), compressedLen: totalLen };
    } catch (e) {
      return { ok: false, error: String(e) };
    }
  });
  console.log("manual encodeShareUrl result:", result);
  expect(result.ok).toBe(true);
});

// ── Real tests ────────────────────────────────────────────────────────────────

test.describe("share URL", () => {
  test("URL hash is set on load and updates when filters change", async ({
    page,
  }) => {
    await expect
      .poll(() => page.evaluate(() => window.location.hash), { timeout: 5000 })
      .toMatch(/^#/);

    const hashBefore = await page.evaluate(() => window.location.hash);

    await page
      .getByRole("button", { name: /add filter/i })
      .first()
      .click();
    await page.locator(".add-filter-menu").getByText("Callsign").click();
    await page.getByPlaceholder("^BAW.*").fill("^BAW");

    await expect
      .poll(() => page.evaluate(() => window.location.hash), { timeout: 3000 })
      .not.toBe(hashBefore);
  });

  test("copy-link button copies the full URL including hash", async ({
    page,
  }) => {
    await expect
      .poll(() => page.evaluate(() => window.location.hash), { timeout: 5000 })
      .toMatch(/^#/);

    await page.getByTitle("Copy share link").click();

    const clipboard = await page.evaluate(() => navigator.clipboard.readText());
    expect(clipboard).toMatch(/^http/);
    expect(clipboard).toContain("#");

    const hash = await page.evaluate(() => window.location.hash);
    expect(clipboard).toContain(hash);
  });

  test("loading a share URL restores filter state", async ({ page }) => {
    await page
      .getByRole("button", { name: /add filter/i })
      .first()
      .click();
    await page.locator(".add-filter-menu").getByText("Callsign").click();
    await page.getByPlaceholder("^BAW.*").fill("^BAW");

    await expect
      .poll(() => page.evaluate(() => window.location.hash), { timeout: 5000 })
      .toMatch(/^#/);

    const shareHash = await page.evaluate(() => window.location.hash);

    await page.goto(`/${shareHash}`);
    await page.waitForSelector("canvas", { timeout: 10_000 });

    await expect(page.getByPlaceholder("^BAW.*")).toHaveValue("^BAW");
  });
});
