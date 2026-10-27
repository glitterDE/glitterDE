/* glitterDE patch for YAD 0.40.0: dialogs wear the glitterDE look (soft glass lavender, pill buttons, rounded fields).
 *
 * The style is plain GTK CSS applied at user priority right after gtk_init(). Order of sources:
 *   1. $YAD_GLITTER_CSS                      (a file; for experiments)
 *   2. $XDG_CONFIG_HOME/glitterde/yad.css    (the user's own tweaks, loaded on top of the built-in style)
 *   3. the built-in style below
 * Set YAD_NO_GLITTER=1 to get stock YAD looks. */
#include <gtk/gtk.h>
#include <stdlib.h>
#include "yad.h"

static const gchar *builtin_css =
  "window, dialog, .background { background-color: #ece6fa; color: #2a2d6e; font-size: 10.5pt; }\n"
  "window.csd, decoration { border-radius: 16px; }\n"
  "headerbar, .titlebar { background-image: none; background-color: #d9d0f7; color: #2a2d6e; border-radius: 16px 16px 0 0; box-shadow: none; border: none; }\n"
  "label { color: #2a2d6e; }\n"
  "button { background-image: none; background-color: rgba(255,255,255,0.75); color: #2a2d6e; border: 1px solid rgba(122,130,255,0.35);\n"
  "         border-radius: 999px; padding: 6px 18px; box-shadow: none; text-shadow: none; }\n"
  "button:hover { background-color: rgba(122,130,255,0.25); }\n"
  "button:active, button:checked { background-color: rgba(122,130,255,0.45); }\n"
  "button.suggested-action, .yad-default button:first-child { background-color: #7a82ff; color: #ffffff; border-color: #7a82ff; font-weight: 700; }\n"
  "entry, spinbutton, combobox button, textview, .view { background-color: rgba(255,255,255,0.88); color: #2a2d6e;\n"
  "                                                   border: 1px solid rgba(122,130,255,0.30); border-radius: 10px; box-shadow: none; }\n"
  "entry:focus, spinbutton:focus { border-color: #7a82ff; }\n"
  "treeview.view:selected, row:selected, .view:selected { background-color: rgba(122,130,255,0.40); color: #2a2d6e; }\n"
  "scrolledwindow { border-radius: 10px; }\n"
  "notebook > header { background-color: transparent; }\n"
  "notebook > header tab { border-radius: 10px; padding: 4px 12px; }\n"
  "notebook > header tab:checked { background-color: rgba(122,130,255,0.35); }\n"
  "progressbar trough { background-color: rgba(122,130,255,0.20); border-radius: 999px; min-height: 8px; }\n"
  "progressbar progress { background-color: #7a82ff; border-radius: 999px; min-height: 8px; }\n"
  "scale trough { background-color: rgba(122,130,255,0.25); border-radius: 999px; }\n"
  "scale highlight { background-color: #7a82ff; border-radius: 999px; }\n"
  "scale slider { background-color: #ffffff; border: 1px solid #7a82ff; border-radius: 999px; }\n"
  "switch { border-radius: 999px; background-color: rgba(122,130,255,0.25); }\n"
  "switch:checked { background-color: #7a82ff; }\n"
  "menu, .menu, popover { background-color: #ece6fa; border-radius: 12px; }\n"
  "menuitem:hover { background-color: rgba(122,130,255,0.30); }\n"
  "check, radio { background-image: none; background-color: rgba(255,255,255,0.92); border: 1px solid rgba(122,130,255,0.55); border-radius: 6px;\n"
  "               color: #ffffff; min-width: 16px; min-height: 16px; box-shadow: none; -gtk-icon-source: none; }\n"
  "radio { border-radius: 999px; }\n"
  "check:checked, radio:checked { background-color: #7a82ff; border-color: #7a82ff; -gtk-icon-source: -gtk-icontheme('object-select-symbolic'); }\n"
  "radio:checked { -gtk-icon-source: -gtk-icontheme('media-record-symbolic'); }\n"
  "textview text, text { color: #2a2d6e; }\n"
  "textview, textview text { background-color: rgba(255,255,255,0.88); }\n"
  "calendar { background-color: rgba(255,255,255,0.88); border-radius: 10px; color: #2a2d6e; }\n"
  "calendar:selected { background-color: #7a82ff; color: #ffffff; border-radius: 999px; }\n"
  "colorswatch { border-radius: 8px; }\n"
  "frame > border { border-color: rgba(122,130,255,0.30); border-radius: 10px; }\n"
  ".cell, treeview.view .cell { border: none; border-radius: 0; background-image: none; background-color: transparent; box-shadow: none; padding: 0; }\n"
  "treeview.view { background-color: rgba(255,255,255,0.88); border: 1px solid rgba(122,130,255,0.30); }\n"
  "treeview.view header button { border-radius: 0; border: none; border-bottom: 1px solid rgba(122,130,255,0.30); padding: 4px 8px;\n"
  "                              background-color: rgba(122,130,255,0.16); font-weight: 700; }\n"
  "selection, entry selection, textview selection { background-color: rgba(122,130,255,0.45); color: #2a2d6e; }\n"
  "separator { background-color: rgba(42,45,110,0.15); }\n";

static void
load_css (const gchar *data, const gchar *file, guint prio)
{
  GtkCssProvider *p = gtk_css_provider_new ();
  GError *err = NULL;

  if (file)
    gtk_css_provider_load_from_path (p, file, &err);
  else
    gtk_css_provider_load_from_data (p, data, -1, &err);

  if (err)
    {
      g_printerr ("yad (glitterDE): style error: %s\n", err->message);
      g_error_free (err);
    }
  else
    gtk_style_context_add_provider_for_screen (gdk_screen_get_default (), GTK_STYLE_PROVIDER (p), prio);
  g_object_unref (p);
}

void
yad_glitter_theme (void)
{
  const gchar *env = g_getenv ("YAD_GLITTER_CSS");
  gchar *user;

  if (g_getenv ("YAD_NO_GLITTER") || !gdk_screen_get_default ())
    return;

  if (env && g_file_test (env, G_FILE_TEST_IS_REGULAR))
    {
      load_css (NULL, env, GTK_STYLE_PROVIDER_PRIORITY_USER);
      return;
    }

  load_css (builtin_css, NULL, GTK_STYLE_PROVIDER_PRIORITY_USER);

  user = g_build_filename (g_get_user_config_dir (), "glitterde", "yad.css", NULL);
  if (g_file_test (user, G_FILE_TEST_IS_REGULAR))
    load_css (NULL, user, GTK_STYLE_PROVIDER_PRIORITY_USER + 1);
  g_free (user);

  g_object_set (gtk_settings_get_default (), "gtk-application-prefer-dark-theme", FALSE, NULL);
}
