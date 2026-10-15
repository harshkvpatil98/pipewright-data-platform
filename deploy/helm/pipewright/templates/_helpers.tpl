{{/* Common naming and labels. */}}

{{- define "pipewright.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "pipewright.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "pipewright.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "pipewright.labels" -}}
app.kubernetes.io/name: {{ include "pipewright.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{/* The Secret name components read env from: an operator-managed one, or ours. */}}
{{- define "pipewright.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "pipewright.fullname" .) -}}
{{- end -}}
{{- end -}}

{{- define "pipewright.configName" -}}
{{- printf "%s-config" (include "pipewright.fullname" .) -}}
{{- end -}}

{{/* The full image refs. tag is required so a release never deploys "latest". */}}
{{- define "pipewright.gatewayImage" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion -}}
{{- printf "%s/%s:%s" .Values.image.registry .Values.image.gatewayRepository $tag -}}
{{- end -}}

{{- define "pipewright.webImage" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion -}}
{{- printf "%s/%s:%s" .Values.image.registry .Values.image.webRepository $tag -}}
{{- end -}}

{{/* envFrom the shared config + secret, used by every workload. */}}
{{- define "pipewright.envFrom" -}}
- configMapRef:
    name: {{ include "pipewright.configName" . }}
- secretRef:
    name: {{ include "pipewright.secretName" . }}
{{- end -}}

{{/*
Stored files. With storage.backend=local every pod that reads or writes them
mounts the same volume at the image's data folder; with s3 there is nothing to
mount. The checks stop a configuration that would split files across pods.
*/}}
{{- define "pipewright.storageChecks" -}}
{{- if eq .Values.storage.backend "s3" -}}
{{- if not .Values.storage.s3.bucket -}}
{{- fail "storage.backend is s3: set storage.s3.bucket to the bucket that holds stored files." -}}
{{- end -}}
{{- else if eq .Values.storage.backend "local" -}}
{{- if and (not .Values.storage.persistence.existingClaim) (ne .Values.storage.persistence.accessMode "ReadWriteMany") -}}
{{- fail "storage.backend is local: the gateway, worker and ticker pods share one volume, which needs storage.persistence.accessMode ReadWriteMany (or an existingClaim that is). Use storage.backend s3 if the cluster has no ReadWriteMany class." -}}
{{- end -}}
{{- else -}}
{{- fail "storage.backend must be local or s3." -}}
{{- end -}}
{{- end -}}

{{- define "pipewright.filesClaim" -}}
{{- .Values.storage.persistence.existingClaim | default (printf "%s-files" (include "pipewright.fullname" .)) -}}
{{- end -}}

{{- define "pipewright.filesMount" -}}
{{- if eq .Values.storage.backend "local" }}
volumeMounts:
  - name: files
    mountPath: /app/apps/api-gateway/data
{{- end }}
{{- end -}}

{{- define "pipewright.filesVolume" -}}
{{- if eq .Values.storage.backend "local" }}
volumes:
  - name: files
    persistentVolumeClaim:
      claimName: {{ include "pipewright.filesClaim" . }}
{{- end }}
{{- end -}}

{{/*
The same settings as an env list, for the migration job (A9, Z4). The job is
a pre-install hook, so it runs before the release's ConfigMap and Secret
exist; reading them would fail every first install. It takes its settings
from the values instead, and an existing Secret (made before the install)
by reference.
*/}}
{{- define "pipewright.hookEnv" -}}
{{- range $key, $value := .Values.config }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
- name: STORAGE_BACKEND
  value: {{ .Values.storage.backend | quote }}
{{- if eq .Values.storage.backend "s3" }}
- name: STORAGE_S3_BUCKET
  value: {{ .Values.storage.s3.bucket | quote }}
- name: STORAGE_S3_PREFIX
  value: {{ .Values.storage.s3.prefix | quote }}
- name: STORAGE_S3_ENDPOINT_URL
  value: {{ .Values.storage.s3.endpointUrl | quote }}
- name: STORAGE_S3_REGION
  value: {{ .Values.storage.s3.region | quote }}
{{- end }}
{{- if not .Values.secrets.existingSecret }}
{{- range $key := list "DATABASE_URL" "AUTH_JWT_SECRET" "AUTH_BOOTSTRAP_USERNAME" "AUTH_BOOTSTRAP_PASSWORD" "STORAGE_ENCRYPTION_KEY" "STORAGE_S3_ACCESS_KEY_ID" "STORAGE_S3_SECRET_ACCESS_KEY" "APP_SECRET_ENCRYPTION_KEY" }}
{{- with index $.Values.secrets $key }}
- name: {{ $key }}
  value: {{ . | quote }}
{{- end }}
{{- end }}
{{- end }}
{{- end -}}
