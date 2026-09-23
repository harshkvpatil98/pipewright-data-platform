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
