# Bulk Actor Import - User Guide

## Quick Start

**Goal**: Import multiple actors (8-15 seed actors) to a query design at once.

**Time**: 2-3 minutes for 10-15 actors.

## Step-by-Step Instructions

### Step 1: Open Query Design Editor

1. Navigate to **Query Designs** in the main navigation
2. Click on an existing query design or create a new one
3. Scroll to the **Actor List** panel

### Step 2: Switch to Bulk Add Mode

1. Look for the toggle buttons at the top of the Actor List panel
2. Click **"Bulk Add"** (Single Add is selected by default)
3. The form will change from a single-line input to a textarea

### Step 3: Prepare Your Actor List

You have two format options:

#### Option A: Simple Format (Recommended for quick imports)

One actor name per line. All actors will be tagged as "person" type.

```
Lars Løkke Rasmussen
Mette Frederiksen
Pernille Vermund
```

#### Option B: Structured Format (For mixed actor types)

Format: `name | type`

```
Lars Løkke Rasmussen | person
Socialdemokratiet | political_party
DR | media_outlet
DLF | teachers_union
```

**Valid actor types:**
- `person` - Individual people
- `organization` - General organizations
- `political_party` - Political parties
- `educational_institution` - Schools, universities
- `teachers_union` - Teachers' unions (DLF, GL, etc.)
- `think_tank` - Think tanks and research institutes
- `media_outlet` - News outlets, TV stations
- `government_body` - Ministries, government agencies
- `ngo` - Non-governmental organizations
- `company` - Private companies
- `unknown` - Unknown type

### Step 4: Add Comments (Optional)

Use `#` at the start of a line to add comments. Comments are ignored during import.

```
# Danish political leaders
Lars Løkke Rasmussen | person
Mette Frederiksen | person

# Political parties
Socialdemokratiet | political_party
Venstre | political_party
```

### Step 5: Paste or Type Your Data

1. Click in the textarea
2. Paste your prepared list (Ctrl+V / Cmd+V)
3. Or type directly in the textarea
4. Review the help text below the textarea for format reminders

### Step 6: Import Actors

1. Click the **"Import Actors"** button (blue button on the right)
2. Wait for validation (button will show spinner and "Importing...")
3. If there are errors:
   - Fix the indicated line number
   - Click "Import Actors" again
4. If successful:
   - You'll see a green message: "Added X actors, skipped Y duplicates"
   - The page will automatically reload after 1 second
   - All actors will appear in the Actor List below

### Step 7: Verify Import

After the page reloads:
1. Check the actor count at the top right of the Actor List panel
2. Scroll through the list to verify all actors are present
3. Each actor should have the correct type badge (Person, Org, Media, etc.)

## Common Use Cases

### Use Case 1: Political Research Project

You're studying a debate involving politicians, parties, and media outlets.

```
# Core politicians
Lars Løkke Rasmussen | person
Mette Frederiksen | person
Pernille Vermund | person

# Political parties
Socialdemokratiet | political_party
Venstre | political_party
Nye Borgerlige | political_party

# Media outlets
DR | media_outlet
TV2 | media_outlet
Politiken | media_outlet
```

### Use Case 2: Education Policy Tracking

You're tracking actors in the Danish education debate.

```
# Government bodies
Undervisningsministeriet | government_body
Børne- og Undervisningsudvalget | government_body

# Teachers' unions
DLF | teachers_union
GL | teachers_union

# Think tanks
CEPOS | think_tank
DEA | think_tank

# Educational institutions
Københavns Universitet | educational_institution
Aarhus Universitet | educational_institution
```

### Use Case 3: Quick Person-Only Import

You have a list of individual commentators or experts.

```
Anders Fogh Rasmussen
Helle Thorning-Schmidt
Kristian Thulesen Dahl
Morten Østergaard
Pia Olsen Dyhr
```

All will be imported as "person" type.

## Troubleshooting

### Error: "Actor name must not be empty"

**Cause**: You have a line with a pipe but no name before it.

**Example of bad input:**
```
| person
```

**Fix:** Add a name before the pipe or delete the line.

### Error: "Invalid actor type: xyz"

**Cause**: The type you specified is not in the valid types list.

**Example of bad input:**
```
Lars Løkke Rasmussen | politician
```

**Fix:** Use `person` instead of `politician`. See Step 3 for valid types.

### Error: "No valid actors found"

**Cause**: Your textarea is empty or contains only comments/empty lines.

**Fix:** Add at least one actor name.

### Actors are skipped

**Behavior**: This is normal! Actors already in the list are skipped automatically.

**Message:** "Added 5 actors, skipped 3 duplicates"

This means 3 actors were already in your list and weren't added again.

## Tips and Best Practices

1. **Prepare in a text editor first**: Use a text editor or spreadsheet to prepare your list, then paste it all at once.

2. **Use comments for organization**: Group related actors with comment headers for easier maintenance.

3. **Double-check actor types**: Make sure you use the correct type from the valid list. Wrong types will cause import to fail.

4. **Start with simple format**: If all your actors are people, just list names (one per line).

5. **Review before importing**: Scan your list once before clicking "Import Actors" to catch any obvious errors.

6. **Keep a backup**: Save your actor list in a separate file so you can re-import if needed.

7. **Import incrementally**: For very large lists (50+ actors), consider importing in batches of 15-20 to make verification easier.

## Keyboard Shortcuts

- **Ctrl/Cmd + A**: Select all text in textarea
- **Ctrl/Cmd + C**: Copy selected text
- **Ctrl/Cmd + V**: Paste text
- **Tab**: Switch to "Import Actors" button
- **Enter** (when button is focused): Submit import

## Related Features

- **Single Add Mode**: For adding one actor at a time (default mode)
- **Actor Directory**: View all actors across all query designs at `/actors`
- **Snowball Sampling**: Discover related actors based on your seed actors
- **Entity Resolution**: Link actor identities across platforms

## Need Help?

If you encounter issues not covered in this guide:
1. Check the inline error messages (they show line numbers)
2. Verify your format matches the examples
3. Try importing a smaller test batch first
4. Contact your system administrator or see the technical documentation
