import "@testing-library/jest-dom";

// jsdom doesn't implement scrollIntoView — stub it out globally.
window.HTMLElement.prototype.scrollIntoView = () => {};

// jsdom doesn't implement matchMedia — stub it out so components using useMobile work.
window.matchMedia = (query: string): MediaQueryList => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: () => {},
  removeListener: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
  dispatchEvent: () => false,
});

// jsdom doesn't ship CompressionStream/DecompressionStream; forward from Node.
if (!("CompressionStream" in window)) {
  Object.assign(window, { CompressionStream, DecompressionStream });
}
