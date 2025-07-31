//
// Copyright © 2025 Agora
// This file is part of TEN Framework, an open source project.
// Licensed under the Apache License, Version 2.0, with certain conditions.
// Refer to the "LICENSE" file in the root directory for more information.
//

import { zodResolver } from "@hookform/resolvers/zod";
import {
  BrushCleaningIcon,
  FolderIcon,
  FolderMinusIcon,
  FolderPlusIcon,
  FolderSyncIcon,
  HardDriveDownloadIcon,
  PlayIcon,
} from "lucide-react";
import * as React from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";
import {
  postCreateApp,
  postReloadApps,
  postUnloadApps,
  retrieveTemplatePkgs,
  useFetchAppScripts,
  useFetchApps,
} from "@/api/services/apps";
import { useGraphs } from "@/api/services/graphs";
import { AppFileManager } from "@/components/file-manager/app-folder";
import {
  AppFolderPopupTitle,
  AppRunPopupTitle,
} from "@/components/popup/default/app";
import { LogViewerPopupTitle } from "@/components/popup/log-viewer";
import { SpinnerLoading } from "@/components/status/loading";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { TEN_PATH_WS_BUILTIN_FUNCTION } from "@/constants";
import { getWSEndpointFromWindow } from "@/constants/utils";
import {
  APP_FOLDER_WIDGET_ID,
  APP_RUN_WIDGET_ID,
  CONTAINER_DEFAULT_ID,
  GROUP_LOG_VIEWER_ID,
} from "@/constants/widgets";
import { cn } from "@/lib/utils";
import { useDialogStore, useFlowStore, useWidgetStore } from "@/store";
import {
  AppCreateReqSchema,
  ETemplateLanguage,
  ETemplateType,
  TemplatePkgsReqSchema,
} from "@/types/apps";
import {
  EDefaultWidgetType,
  ELogViewerScriptType,
  EWidgetCategory,
  EWidgetDisplayType,
} from "@/types/widgets";

export const AppsManagerWidget = (props: { className?: string }) => {
  const [isUnloading, setIsUnloading] = React.useState<boolean>(false);
  const [isReloading, setIsReloading] = React.useState<boolean>(false);

  const { t } = useTranslation();
  const { data: loadedApps, isLoading, error, mutate } = useFetchApps();
  const { mutate: reloadGraphs } = useGraphs();
  const { appendWidget, removeBackstageWidget, removeLogViewerHistory } =
    useWidgetStore();
  const { setNodesAndEdges } = useFlowStore();
  const { appendDialog, removeDialog } = useDialogStore();

  const openAppFolderPopup = () => {
    appendWidget({
      container_id: CONTAINER_DEFAULT_ID,
      group_id: APP_FOLDER_WIDGET_ID,
      widget_id: APP_FOLDER_WIDGET_ID,

      category: EWidgetCategory.Default,
      display_type: EWidgetDisplayType.Popup,

      title: <AppFolderPopupTitle />,
      metadata: {
        type: EDefaultWidgetType.AppFolder,
      },
      popup: {
        width: 0.5,
        height: 0.8,
      },
    });
  };

  const handleUnloadApp = async (baseDir: string) => {
    try {
      setIsUnloading(true);
      await postUnloadApps(baseDir);
      toast.success(t("header.menuApp.unloadAppSuccess"));
    } catch (error) {
      console.error(error);
      toast.error(
        t("header.menuApp.unloadAppFailed", {
          description:
            error instanceof Error ? error.message : t("popup.apps.error"),
        })
      );
    } finally {
      await mutate();
      await reloadGraphs();
      setIsUnloading(false);
    }
  };

  const handleReloadApp = async (baseDir?: string) => {
    appendDialog({
      id: "reload-app",
      title: baseDir
        ? t("header.menuApp.reloadApp")
        : t("header.menuApp.reloadAllApps"),
      content: (
        <div className={cn("flex flex-col gap-2", "text-sm")}>
          <p className="">
            {baseDir
              ? t("header.menuApp.reloadAppConfirmation", {
                  name: baseDir,
                })
              : t("header.menuApp.reloadAllAppsConfirmation")}
          </p>
          <p>{t("header.menuApp.reloadAppDescription")}</p>
        </div>
      ),
      onCancel: async () => {
        removeDialog("reload-app");
      },
      onConfirm: async () => {
        await reloadApps(baseDir);
        await reloadGraphs();
        removeDialog("reload-app");
      },
    });
  };

  const reloadApps = async (baseDir?: string) => {
    try {
      setIsReloading(true);
      await postReloadApps(baseDir);
      if (baseDir) {
        toast.success(t("header.menuApp.reloadAppSuccess"));
      } else {
        toast.success(t("header.menuApp.reloadAllAppsSuccess"));
      }
    } catch (error) {
      console.error(error);
      if (baseDir) {
        toast.error(
          t("header.menuApp.reloadAppFailed", {
            description:
              error instanceof Error ? error.message : t("popup.apps.error"),
          })
        );
      } else {
        toast.error(
          t("header.menuApp.reloadAllAppsFailed", {
            description:
              error instanceof Error ? error.message : t("popup.apps.error"),
          })
        );
      }
    } finally {
      await mutate();
      await reloadGraphs();
      setNodesAndEdges([], []);
      setIsReloading(false);
    }
  };

  const handleAppInstallAll = (baseDir: string) => {
    const widgetId = "app-install-" + Date.now();
    appendWidget({
      container_id: CONTAINER_DEFAULT_ID,
      group_id: GROUP_LOG_VIEWER_ID,
      widget_id: widgetId,

      category: EWidgetCategory.LogViewer,
      display_type: EWidgetDisplayType.Popup,

      title: <LogViewerPopupTitle />,
      metadata: {
        wsUrl: getWSEndpointFromWindow() + TEN_PATH_WS_BUILTIN_FUNCTION,
        scriptType: ELogViewerScriptType.INSTALL_ALL,
        script: {
          type: ELogViewerScriptType.INSTALL_ALL,
          base_dir: baseDir,
        },
        options: {
          disableSearch: true,
          title: t("popup.logViewer.appInstall"),
        },
        postActions: async () => {
          await reloadApps(baseDir);
        },
      },
      popup: {
        width: 0.5,
        height: 0.8,
      },
      actions: {
        onClose: () => {
          removeBackstageWidget(widgetId);
        },
        custom_actions: [
          {
            id: "app-start-log-clean",
            label: t("popup.logViewer.cleanLogs"),
            Icon: BrushCleaningIcon,
            onClick: () => {
              removeLogViewerHistory(widgetId);
            },
          },
        ],
      },
    });
  };

  const handleRunApp = (baseDir: string, scripts: string[]) => {
    appendWidget({
      container_id: CONTAINER_DEFAULT_ID,
      group_id: APP_RUN_WIDGET_ID,
      widget_id: APP_RUN_WIDGET_ID + "-" + baseDir,

      category: EWidgetCategory.Default,
      display_type: EWidgetDisplayType.Popup,

      title: <AppRunPopupTitle />,
      metadata: {
        type: EDefaultWidgetType.AppRun,
        base_dir: baseDir,
        scripts: scripts,
      },
    });
  };

  const isLoadingMemo = React.useMemo(() => {
    return isUnloading || isReloading || isLoading;
  }, [isUnloading, isReloading, isLoading]);

  React.useEffect(() => {
    if (error) {
      toast.error(t("popup.apps.error"));
    }
  }, [error]);

  return (
    <div
      className={cn(
        "flex h-full w-full flex-col gap-2 overflow-y-auto",
        props.className
      )}
    >
      <Table>
        <TableCaption className="select-none">
          {t("popup.apps.tableCaption")}
        </TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead className="w-14">{t("dataTable.no")}</TableHead>
            <TableHead>{t("dataTable.name")}</TableHead>
            <TableHead className="text-right">
              {t("dataTable.actions")}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableRow>
              <TableCell colSpan={3}>
                <SpinnerLoading />
              </TableCell>
            </TableRow>
          ) : (
            loadedApps?.app_info?.map((app, index) => (
              <TableRow key={app.base_dir}>
                <TableCell className="font-medium">{index + 1}</TableCell>
                <TableCell>
                  <span className={cn("rounded-md bg-muted p-1 px-2 text-xs")}>
                    {app.base_dir}
                  </span>
                </TableCell>
                <AppRowActions
                  baseDir={app.base_dir}
                  isLoading={isLoadingMemo}
                  handleUnloadApp={handleUnloadApp}
                  handleReloadApp={handleReloadApp}
                  handleAppInstallAll={handleAppInstallAll}
                  handleRunApp={handleRunApp}
                />
              </TableRow>
            ))
          )}
        </TableBody>
        <TableFooter className="bg-transparent">
          <TableRow>
            <TableCell colSpan={3} className="space-x-2 text-right">
              <Button
                variant="outline"
                size="sm"
                onClick={openAppFolderPopup}
                disabled={isLoadingMemo}
              >
                <FolderPlusIcon className="h-4 w-4" />
                {t("header.menuApp.loadApp")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={isLoadingMemo}
                onClick={() => handleReloadApp()}
              >
                <FolderSyncIcon className="h-4 w-4" />
                <span>{t("header.menuApp.reloadAllApps")}</span>
              </Button>
            </TableCell>
          </TableRow>
        </TableFooter>
      </Table>
    </div>
  );
};

const AppRowActions = (props: {
  baseDir: string;
  isLoading?: boolean;
  handleUnloadApp: (baseDir: string) => void;
  handleReloadApp: (baseDir: string) => void;
  handleAppInstallAll: (baseDir: string) => void;
  handleRunApp: (baseDir: string, scripts: string[]) => void;
}) => {
  const {
    baseDir,
    isLoading,
    handleUnloadApp,
    handleReloadApp,
    handleAppInstallAll,
    handleRunApp,
  } = props;

  const { t } = useTranslation();
  const {
    data: scripts,
    isLoading: isScriptsLoading,
    error: scriptsError,
  } = useFetchAppScripts(baseDir);

  React.useEffect(() => {
    if (scriptsError) {
      toast.error(t("popup.apps.error"), {
        description:
          scriptsError instanceof Error
            ? scriptsError.message
            : t("popup.apps.error"),
      });
    }
  }, [scriptsError]);

  return (
    <TableCell className="flex items-center gap-2 text-right">
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="icon"
              disabled={isLoading}
              onClick={() => handleUnloadApp(baseDir)}
            >
              <FolderMinusIcon className="h-4 w-4" />
              <span className="sr-only">{t("header.menuApp.unloadApp")}</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>{t("header.menuApp.unloadApp")}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="icon"
              disabled={isLoading}
              onClick={() => handleReloadApp(baseDir)}
            >
              <FolderSyncIcon className="h-4 w-4" />
              <span className="sr-only">{t("header.menuApp.reloadApp")}</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>{t("header.menuApp.reloadApp")}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="icon"
              disabled={isLoading}
              onClick={() => handleAppInstallAll(baseDir)}
            >
              <HardDriveDownloadIcon className="h-4 w-4" />
              <span className="sr-only">{t("header.menuApp.installAll")}</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>{t("header.menuApp.installAll")}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="icon"
              disabled={isLoading || isScriptsLoading || scripts?.length === 0}
              onClick={() => {
                handleRunApp(baseDir, scripts);
              }}
            >
              {isScriptsLoading ? (
                <SpinnerLoading className="size-4" />
              ) : (
                <PlayIcon className="size-4" />
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>{t("header.menuApp.runApp")}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </TableCell>
  );
};
