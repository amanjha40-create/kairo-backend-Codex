/**
 * Accessible confirmation dialog for leaving a case with session-only
 * changes. Replaces the previous `window.confirm()` prompt so screen
 * readers and keyboard users get the same experience, and so the copy
 * clearly explains what "session-only" means.
 */
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

export interface UnsavedChangesDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  /** Optional list of change categories to render as a bullet list. */
  changes?: string[];
}

export function UnsavedChangesDialog({
  open,
  onOpenChange,
  onConfirm,
  changes,
}: UnsavedChangesDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Leave this case?</AlertDialogTitle>
          <AlertDialogDescription>
            You have session-only changes on this workspace. They are not saved to the backend and
            will be discarded if you leave the page or reload the browser.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {changes && changes.length > 0 ? (
          <ul className="ml-5 list-disc space-y-0.5 text-xs text-muted-foreground">
            {changes.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel>Stay on case</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          >
            Discard and leave
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
