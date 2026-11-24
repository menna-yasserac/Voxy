# Security Test Cases

## Test Cases

| Test Case ID | Scenario | Test Steps | Expected Result |
|---|---|---|---|
| TC-01 | Create a file inside Home | Request creation of a file in the Home directory. | The file is created successfully. |
| TC-02 | Create a folder inside Home | Request creation of a folder in the Home directory. | The folder is created successfully. |
| TC-03 | Create a file outside Home | Request creation of a file outside the Home directory. | The operation is rejected. |
| TC-04 | Create a folder outside Home | Request creation of a folder outside the Home directory. | The operation is rejected. |
| TC-05 | Request deletion of a file inside Home | Select a file inside Home for deletion. | A confirmation message is displayed before deletion. |
| TC-06 | Confirm file deletion | Select **Confirm** in the deletion prompt. | The selected file is deleted. |
| TC-07 | Cancel file deletion | Select **Cancel** in the deletion prompt. | The file is not deleted. |
| TC-08 | Request deletion of a folder inside Home | Select a folder inside Home for deletion. | A confirmation message is displayed before deletion. |
| TC-09 | Confirm folder deletion | Select **Confirm** in the deletion prompt. | The selected folder is deleted, provided it is not protected. |
| TC-10 | Cancel folder deletion | Select **Cancel** in the deletion prompt. | The folder is not deleted. |
| TC-11 | Delete an item outside Home | Request deletion of a file or folder outside Home. | The operation is rejected. |
| TC-12 | Protect the Downloads folder | Request deletion of the exact folder name `Downloads` inside Home. | Deletion is blocked because `Downloads` is protected. |
| TC-13 | Protect the Documents folder | Request deletion of the exact folder name `Documents` inside Home. | Deletion is blocked. |
| TC-14 | Protect the Desktop folder | Request deletion of the exact folder name `Desktop` inside Home. | Deletion is blocked. |
| TC-15 | Protect the Pictures folder | Request deletion of the exact folder name `Pictures` inside Home. | Deletion is blocked. |
| TC-16 | Protect the Music folder | Request deletion of the exact folder name `Music` inside Home. | Deletion is blocked. |
| TC-17 | Protect the Videos folder | Request deletion of the exact folder name `Videos` inside Home. | Deletion is blocked. |
| TC-18 | Check lowercase `downloads` | Request deletion of a folder named `downloads` (lowercase) inside Home. | It is not treated as the protected `Downloads` folder; a confirmation message is displayed. |
| TC-19 | Confirm deletion of lowercase `downloads` | Select **Confirm** for the `downloads` folder. | The folder is deleted if the path is valid and inside Home. |
| TC-20 | Cancel deletion of lowercase `downloads` | Select **Cancel** for the `downloads` folder. | The folder remains unchanged. |
| TC-21 | Close an item with unsaved changes | Modify a file or item without saving, then request to close it. | A confirmation message is displayed before closing. |
| TC-22 | Confirm closing an item with unsaved changes | Select **Confirm** in the close confirmation prompt. | The application proceeds with the configured close behavior. |
| TC-23 | Cancel closing an item with unsaved changes | Select **Cancel** in the close confirmation prompt. | The item remains open and the user can continue working. |
| TC-24 | Close an item with no unsaved changes | Request to close an item when there is nothing to save. | The item closes normally without displaying a confirmation message. |
| TC-25 | Verify deletion confirmation details | Request deletion of a specific file or folder. | The confirmation message identifies the correct target. |
| TC-26 | Prevent deletion before confirmation | Request deletion, but do not confirm it. | No deletion occurs before explicit confirmation. |

## Important Validation Notes

- File and folder creation must be allowed only inside the user's Home directory.
- Deletion must be allowed only for valid targets inside the user's Home directory.
- The protected folder names are case-sensitive: `Downloads`, `Documents`, `Desktop`, `Pictures`, `Music`, and `Videos`.
- A folder named `downloads` (all lowercase) is different from `Downloads` and is not protected by the exact-name rule.
- The resolved path should be validated to prevent path traversal (for example, using `..`) from escaping the Home directory.
- A deletion confirmation must appear before the deletion is performed.
- If the user cancels a deletion, no deletion should take place.
- A confirmation must appear before closing an item that has unsaved changes.
- If the user cancels closing, the item should remain open.


