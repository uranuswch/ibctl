{{- define "ibctl.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ibctl.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := include "ibctl.name" . -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "ibctl.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ibctl.labels" -}}
helm.sh/chart: {{ include "ibctl.chart" . }}
app.kubernetes.io/name: {{ include "ibctl.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "ibctl.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ibctl.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "ibctl.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "ibctl.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "ibctl.secretName" -}}
{{- printf "%s-secret" (include "ibctl.fullname" .) -}}
{{- end -}}

{{- define "ibctl.pvcName" -}}
{{- printf "%s-jts" (include "ibctl.fullname" .) -}}
{{- end -}}

