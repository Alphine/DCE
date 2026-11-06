// Role helpers. Mirrors docs/api.md §1–2 and SDD §20.5. The backend enforces every rule;
// these checks only decide which controls are shown.

export const ROLE_ORDER = ['Viewer', 'Analyst', 'Reviewer', 'Approver', 'Admin'];

export function hasRole(user, minRole) {
  if (!user) return false;
  const have = ROLE_ORDER.indexOf(user.role);
  const need = ROLE_ORDER.indexOf(minRole);
  return have >= 0 && have >= need;
}

// Works for any object with an owner {id}: datasets, agent tasks.
export function isOwner(user, obj) {
  const ownerId = obj && obj.owner ? obj.owner.id : null;
  return !!user && !!ownerId && ownerId === user.id;
}

export const can = {
  upload: (u) => hasRole(u, 'Analyst'),
  createTask: (u) => hasRole(u, 'Analyst'),
  // Reviewer+ and not the uploader (docs/api.md §2)
  approveDataset: (u, ds) => hasRole(u, 'Reviewer') && !isOwner(u, ds),
  // Gate A: Approver and above, not the requester
  gateA: (u, task) => hasRole(u, 'Approver') && !isOwner(u, task),
  // Gate B: Reviewer and above, not the requester
  gateB: (u, task) => hasRole(u, 'Reviewer') && !isOwner(u, task),
  // Owner or Admin
  cancel: (u, task) => isOwner(u, task) || hasRole(u, 'Admin'),
  audit: (u) => hasRole(u, 'Reviewer'),
  verifyAudit: (u) => hasRole(u, 'Admin'),
  allTasks: (u) => hasRole(u, 'Reviewer'),
};
