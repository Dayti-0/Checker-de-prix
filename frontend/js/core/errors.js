// Errors shown to the user.

import { ApiError } from "./api.js";

// French message of any error (never a technical one)
export function errorMessage(err) {
    if (err instanceof ApiError) return err.message;
    return "Une erreur inattendue s'est produite. Rechargez la page.";
}
