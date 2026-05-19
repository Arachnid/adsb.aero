import "@testing-library/jest-dom";

// jsdom doesn't implement scrollIntoView — stub it out globally.
window.HTMLElement.prototype.scrollIntoView = () => {};

// jsdom doesn't ship CompressionStream/DecompressionStream; forward from Node.
if (!("CompressionStream" in window)) {
  Object.assign(window, { CompressionStream, DecompressionStream });
}
