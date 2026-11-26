---
name: building-dinkster-interfaces
description: "Applies Dinkster product design rules and browser interaction checks. Use when building, reviewing or verifying any Dinkster user interface."
---

# UI builder and reviewer

Read the workspace DELEGATION.md first. This is its role-specific policy, not a second checklist. Load only the role you are performing; follow the shared page for cross-role contracts.

## Product design rules

- All Dinkster UIs use the shared design rules, tokens, one stylesheet, one SolidJS component package and gallery. Literal colors/font sizes, raw controls and classes outside the stylesheet fail builds. New patterns enter the gallery in their own change before screens use them; prototype code is a design reference, not production source to copy. User-facing design lands after ordinary gates; user reviews live/QA afterwards and findings become follow-ups. Browser interaction checks still gate landing.

- Button color: add/create cyan `#32E6C5`; remove/revoke/disable coral `#FF7468`; other actions neutral, except a solid screen-primary action (Sign in, Save, Continue) is cyan with dark label. Colored outlines have matching labels; neutral outlines are gray `#7D8792` with light `#F2F4F5` labels. Exact values and the roles table live in the shared rules file read by every flow spec. Verification checks role, outline, fill and label.

- Fill: solid commits the screen's job now with no further step, including a harmless download-only screen; outline opens the next step/confirmation or is a secondary action saving nothing. At most one solid button per screen. Removal from lists opens confirmation via coral outline, then solid coral confirms. Sign out is an exception: coral text plain menu item, immediate, no confirmation. Other session-leaving/removal actions are coral too.

- Bundle and use Noto Sans and Noto Sans Mono under SIL OFL, not system fallback. All text, titles, headings and navigation are sentence case. Labels never wrap or change width on selection.

- Builders may correct wording in user-ruled flow specs in the same PR, listing each edit. Adding/removing screens, states or buttons, changing destinations or button roles/fill/colors needs the user's ruling before building.

- Field problems show under the field. Success is a corner toast with green check, timed hide and close X. Non-field errors are top-of-content coral-icon banners with X, persisting until closed or next successful action. Standing page notices are cyan info-icon banners without X. These message roles live beside button roles. Unconfigured services are hidden from pages/side-panels, not offered then refused.

- Real-browser checks prove menus toggle by click and close on outside click, Escape or selection, with unselectable labels; navigation marks current and changes page immediately, showing loading while data arrives; Save-like buttons stay disabled until dirty and disable after save or undo.

- Deprecated partner models stay selectable and visibly marked until retired; retired models are removed, never listed.
