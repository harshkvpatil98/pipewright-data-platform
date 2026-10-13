# Build

Clean and reshape data, step by step, seeing the result as you go.

## Studio

Pick a dataset and add steps. Your original data is never changed: the Studio shows what the steps would make, and saving keeps the steps as a recipe.

- **Add a step** (or press `/`) searches the common steps and the tool library: filter rows, fix text, split a column, join another dataset and more.
- **Right-click a column** for the steps that suit it, such as "Standardise an email" on an email column.
- **Click a step** to change its settings right under it. Each step says in a few words what it does.
- **Undo** and **redo** take any change back. Clicking a column header only sorts what is on screen; it does not add a step.
- Unsaved work is kept in your browser and offered back next time.
- **Details** shows the columns, where each step runs (at the source or here), the recipe as a file, and comments.

**Start from a template** offers recipes for common jobs, such as tidying a customer list, matched to your columns.

When it looks right, **Save**, then **Run** to make the result a dataset. Run it again any time, or put it on a [schedule](automate.md#schedules).

## Recipes

Every saved recipe. Open one to change its steps in the Studio, or run it to make a fresh result. Each run adds a version to the same result dataset.

## SQL

Write SQL against a connected database and see the results. It only reads unless an administrator allows writing; a statement that would change data asks you to confirm first. Save the queries you use often. You can also ask a dataset version a question in SQL from its version history.

## Notebooks

Mix SQL, recipe and text cells that run top to bottom; each cell can use the results of the cells above it. Python cells run only on servers where they can be kept within safe limits, and the page says when they are off.

## Table editor

Change rows in a connected database table directly. You see every change, and how many rows it affects, before anything is saved, and a change that would touch rows someone else just changed is stopped. Only tables with a clear way to identify each row can be edited.
