declare module "igv" {
  const igv: {
    createBrowser(el: HTMLElement, options: Record<string, unknown>): Promise<any>;
    removeBrowser(browser: any): void;
  };
  export default igv;
}
