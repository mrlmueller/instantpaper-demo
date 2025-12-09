# InstantPaper - TODO List

This file tracks features that were identified during the new design integration but deferred for future implementation.

## Deferred Features (New Design Integration)

### Multi-Project Support
Currently, the app shows multi-project UI elements but only uses a single hardcoded project (`{ id: '1', name: 'Meine Arbeit' }`).

**Backend Tasks:**
- [ ] Add `projektId` field to Firestore schema for all collections
- [ ] Update all Firestore queries to filter by `projektId`
- [ ] Create `projects` collection in Firestore
- [ ] Add Server Actions for project CRUD operations (`app/actions/projects.ts`)
- [ ] Update security rules to scope user data to projects

**Frontend Tasks:**
- [ ] Wire up ProjektHeader project selector to real data
- [ ] Implement project switching functionality
- [ ] Add project creation/deletion dialogs
- [ ] Update Dashboard component to accept `projektId` prop
- [ ] Handle project context throughout the app

**Files to modify:**
- `/app/actions/quellen.ts` - Add projektId filtering
- `/app/actions/kapitels.ts` - Add projektId filtering
- `/app/components/dashboard/ProjektHeader.tsx` - Wire up real handlers
- `/app/components/dashboard/Dashboard.tsx` - Accept projektId prop
- `/firestore.rules` - Update security rules

---

### Profile Page Analytics (Real Data)
Currently, the profile page (`/app/(protected)/profil/page.tsx`) displays mock data only.

**Backend Tasks:**
- [ ] Create `getUserStats()` Server Action to aggregate statistics from Firestore
- [ ] Aggregate total costs across all runs (sum of `cost` fields)
- [ ] Count total kapitels, quellen, and runs per user
- [ ] Calculate total words generated (sum of word counts from results)
- [ ] Group runs by month for activity chart
- [ ] Group costs by project (once multi-project is implemented)
- [ ] Track model usage distribution (gpt-4o-mini, gpt-4o, o1-mini)

**Frontend Tasks:**
- [ ] Replace mock data with real Server Action calls
- [ ] Add loading states during data fetch
- [ ] Handle empty states (new users with no data)
- [ ] Add real-time updates for statistics (optional)

**Files to modify:**
- `/app/actions/user.ts` - Add `getUserStats()` function
- `/app/(protected)/profil/page.tsx` - Replace mock data with real data

---

### Hierarchical Chapter Numbering Enhancements

**Current Implementation:**
- Kapitels support hierarchical numbering (1, 1.1, 1.1.1)
- Input validation exists (3 levels max)
- Visual indentation in sidebar
- `nummer` field defaults to '1' for existing kapitels

**Enhancements to Add:**
- [ ] Auto-suggest next number based on existing kapitels
- [ ] Duplicate nummer validation (prevent two kapitels with same nummer)
- [ ] Auto-sorting by nummer (hierarchical sort: 1 → 1.1 → 1.2 → 2)
- [ ] Renumber children when parent changes (e.g., 1.1 → 2.1 when parent moves)
- [ ] Visual hierarchy improvements (collapsible sections)
- [ ] Drag-and-drop reordering with automatic renumbering

**Files to modify:**
- `/app/components/dashboard/KapitelNavigator.tsx` - Add validation and auto-suggest
- `/app/actions/kapitels.ts` - Add duplicate check, add renumbering logic

---

### Direct Combine Feature Documentation

**Current Implementation:**
- ProcessingDialog has a "Direkt kombinieren" toggle (`directCombine`)
- This maps to `autoCombine` in Firebase
- When enabled, texts are automatically combined after processing

**Missing:**
- [ ] Add tooltip/help text explaining what "Direkt kombinieren" does
- [ ] Add visual indicator showing this setting in the run info
- [ ] Document the difference between manual and automatic combining

**Files to modify:**
- `/app/components/dashboard/ProcessingDialog.tsx` - Add tooltip with explanation

---

## Known Issues

### Cost Unit Inconsistency
- **Issue:** Firebase stores costs in USD dollars, but UI displays in EUR cents
- **Impact:** Cost calculations may be inaccurate, currency mismatch
- **Resolution:**
  - [ ] Standardize on single currency and unit (recommend: cents)
  - [ ] Update all cost storage in Firebase to use cents (migration needed)
  - [ ] Update FastAPI backend to return costs in cents
  - [ ] Ensure consistent cost calculation throughout

**Files affected:**
- `/app/lib/transformers/ui-data.ts` - Cost conversion logic
- `/fastapi/services/quelle_service.py` - Cost calculation
- All components displaying costs

---

### Nummer Field Migration
- **Issue:** Existing kapitels in Firestore don't have `nummer` field
- **Current Fix:** Default to '1' when reading (`transformKapitelToUI()`)
- **Long-term Fix:**
  - [ ] Create migration script to add `nummer` field to all existing kapitels
  - [ ] Implement smart numbering based on `order` field or creation date
  - [ ] Update Firestore rules to require `nummer` field for new kapitels

**Files affected:**
- `/app/lib/transformers/ui-data.ts` - Default value logic
- `/app/actions/kapitels.ts` - Create migration function

---

## Performance Optimizations (Future)

### Real-time Updates
- [ ] Optimize Firestore listener to use pagination for large datasets
- [ ] Implement client-side caching for quellen (reduce reads)
- [ ] Add debouncing to search input in QuellenPanel
- [ ] Use Firestore indexes for faster queries

### Bundle Size
- [ ] Analyze and optimize shadcn component imports (tree-shaking)
- [ ] Lazy load profile page components
- [ ] Code-split Dashboard components for faster initial load

---

## UI/UX Enhancements (Nice to Have)

### Search Enhancements
- [ ] Add fuzzy search to Quellen (current: exact substring match)
- [ ] Search by content, not just name
- [ ] Add search history/suggestions
- [ ] Highlight search terms in results

### Keyboard Shortcuts
- [ ] Cmd/Ctrl+K for global search
- [ ] Cmd/Ctrl+N for new kapitel
- [ ] Arrow keys for kapitel navigation
- [ ] Escape to close panels

### Accessibility
- [ ] Add ARIA labels to all interactive elements
- [ ] Ensure keyboard navigation works throughout
- [ ] Add focus indicators
- [ ] Test with screen readers

### Mobile Responsiveness
- [ ] Optimize 3-panel layout for mobile (collapse to tabs)
- [ ] Make quellen panel full-screen on mobile
- [ ] Add mobile-specific navigation
- [ ] Test on various screen sizes

---

## Testing

### Unit Tests
- [ ] Add tests for data transformers (`/app/lib/transformers/ui-data.ts`)
- [ ] Add tests for Server Actions
- [ ] Add tests for hierarchical numbering logic

### Integration Tests
- [ ] Test kapitel CRUD operations
- [ ] Test quellen assignment/unassignment
- [ ] Test processing workflow end-to-end
- [ ] Test real-time updates

### E2E Tests
- [ ] Add Playwright tests for main user flows
- [ ] Test authentication flow
- [ ] Test dashboard interactions
- [ ] Test profile page

---

## Documentation

- [ ] Update CLAUDE.md with new component structure
- [ ] Document the transformation layer pattern
- [ ] Add architecture diagram showing data flow
- [ ] Document the 3-panel layout system
- [ ] Create developer guide for adding new features

---

## Migration from Old Design

**Components to Remove** (after thorough testing):
- [ ] `/app/components/dashboard/DashboardPanels.tsx`
- [ ] `/app/components/dashboard/DashboardWithSidebar.tsx`
- [ ] `/app/components/kapitels/*` (entire directory)
- [ ] `/app/components/quellen/*` (entire directory)

**Verification Steps:**
1. Test all kapitel operations (create, edit, delete, select)
2. Test all quellen operations (create, delete, assign, search)
3. Test processing workflow with all model types
4. Test profile page navigation
5. Verify real-time updates work correctly
6. Check that no errors appear in browser console
7. Test on different browsers (Chrome, Firefox, Safari)
8. Only then remove old components

---

## Notes

- This TODO list was created during the new design integration (December 2024)
- All deferred features were intentionally postponed to focus on core UI implementation
- Priority should be given to multi-project support and profile analytics
- Cost unit inconsistency should be resolved before adding financial features
