// Features that live outside the views (banners, bell...). Fixed list: a lot
// fills its own module. Each module exports init(), called once at startup
// (unless it exports enabled = false).

import * as accessCode from "./access-code.js";
import * as bell from "./bell.js";
import * as offlineBanner from "./offline-banner.js";
import * as setupBanner from "./setup-banner.js";
import * as updateBanner from "./update-banner.js";

export const FEATURES = { offlineBanner, setupBanner, bell, accessCode, updateBanner };

export function initFeatures() {
    for (const [name, feature] of Object.entries(FEATURES)) {
        if (feature.enabled === false) continue;
        try {
            feature.init();
        } catch (err) {
            console.error(`Module ${name} :`, err);
        }
    }
}
