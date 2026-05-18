import { type Page } from "@playwright/test";

/** X coordinate safely inside the map area (right of the left sidebar). */
export const MAP_X = 450;

/** Vertical midpoint of the default 720-tall Playwright viewport. */
export const MAP_Y_MID = 360;

/** Page-object for the query builder sidebar. */
export class QueryBuilderPage {
  constructor(private page: Page) {}

  get runButton() {
    return this.page.getByRole("button", { name: /run query/i });
  }

  get emptyState() {
    return this.page.getByText("No filters yet.");
  }

  async addFilter(label: string): Promise<void> {
    await this.page
      .getByRole("button", { name: /add filter/i })
      .first()
      .click();
    await this.page
      .locator(".add-filter-menu")
      .getByText(label, { exact: true })
      .click();
  }

  async removeFilter(index = 0): Promise<void> {
    await this.page.getByTitle("Remove filter").nth(index).click();
  }

  async typeCallsignPattern(pattern: string): Promise<void> {
    await this.page.getByPlaceholder("^BAW.*").fill(pattern);
  }

  async openChipDropdown(index = 0): Promise<void> {
    await this.page.getByText("+ choose").nth(index).click();
  }

  async selectChipOption(text: string): Promise<void> {
    await this.page.getByText(text, { exact: true }).click();
  }

  async clickShapeToggle(label: string): Promise<void> {
    await this.page.getByRole("button", { name: label }).click();
  }
}
