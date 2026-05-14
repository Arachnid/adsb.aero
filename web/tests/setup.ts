import "@testing-library/jest-dom";

// jsdom doesn't implement scrollIntoView — stub it out globally.
window.HTMLElement.prototype.scrollIntoView = () => {};
