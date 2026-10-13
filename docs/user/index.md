# Getting started

Pipewright brings your data in, cleans it, checks it and delivers it where it is needed. This page takes you from nothing to a working project in about ten minutes.

## The idea in one minute

Everything lives in a **project**: one team's or one subject's data and work. Inside a project:

- **Data** is where tables arrive, from uploaded files, databases, apps and live feeds.
- **Build** is where you clean and reshape them, step by step, in the **Studio**. Saved steps are a **recipe**.
- **Automate** runs recipes, imports and deliveries by themselves, on a schedule or in a workflow.
- **Trust** checks the data is right, and raises an **incident** when it is not.
- **Share** turns data into charts, dashboards and reports people can read.

The [glossary](glossary.md) explains every word the product uses.

## Your first ten minutes

1. **Make a project.** From Home, choose **New project** and give it a name, such as "Sales".
2. **Add data.** Choose **Add data**. Upload a CSV or Excel file, connect a database, or start with sample data. Pipewright shows how it will read the file before anything is saved.
3. **Clean it.** Open the dataset and choose **Clean in Studio**. Add steps such as "Remove empty rows" or "Standardise an email". The preview updates as you go, and undo takes any step back. Save the steps as a recipe.
4. **Check it.** Under Trust, add a check such as "every order has an email". Run it to see which rows fail.
5. **Automate it.** Put the recipe on a schedule so it runs every morning, or build a workflow that imports, cleans, checks and delivers in order.
6. **Share it.** Under Share, make a chart and put it on a dashboard. Share the dashboard by link or have it emailed.

The checklist on each project's Overview follows the same steps and ticks each one as you finish it.

## Finding your way

- The rail on the left is the open project's areas; each area has tabs along the top.
- **Search** (⌘K, or Ctrl+K on Windows) finds any page, dataset or dashboard by name.
- **About this page** (the question mark beside the tabs) says what the page is for, with a link to its help page here.
- The **Help** menu has this help, keyboard shortcuts, what is new, and how to reach support.

## Getting help

If something does not work as this help says, check [System status](admin.md#system-status) first: a stopped background worker explains most stuck runs. Then contact your administrator, or the support address in the Help menu if your deployment has one. Include what you were doing, the page's address and the time it happened.

## More

- [Overview](overview.md) · [Data](data.md) · [Build](build.md) · [Automate](automate.md) · [Trust](trust.md) · [Share](share.md)
- [Admin guide](admin.md) for people who run Pipewright for others
- [Security](security.md) for a security review
- [Using the API](api.md) for scripts and other systems
- [What's new](whats-new.md)
