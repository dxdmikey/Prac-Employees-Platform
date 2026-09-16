// What the signed-in user is allowed to see.
//
// The React app never decides visibility itself - it asks the backend and
// renders whatever comes back. That is what "metadata-driven" means in
// practice: adding an application to a role in the database changes the menu,
// with no change to this code.

import { apiRequest } from './apiClient.js'

/**
 * Identity, roles, permissions and accessible applications, in one call.
 * This is what the application menu is built from.
 */
export function fetchMyAccess() {
  return apiRequest('/api/access/me')
}

/** The screens this user may open inside one application. */
export function fetchApplicationScreens(applicationCode) {
  return apiRequest(`/api/access/applications/${applicationCode}/screens`)
}

/**
 * The dashboards on a screen, each with its widgets already attached, so a
 * screen renders from a single request.
 */
export function fetchScreenDashboards(screenCode) {
  return apiRequest(`/api/access/screens/${screenCode}/dashboards`)
}

/**
 * Live values for the widgets of a dashboard that declare a data source.
 * Keyed by widget code; merged over each widget's stored config.
 */
export function fetchDashboardData(dashboardCode) {
  return apiRequest(`/api/access/dashboards/${dashboardCode}/data`)
}
