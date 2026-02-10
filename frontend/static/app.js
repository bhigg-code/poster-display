/**
 * Movie Poster Display - Frontend Application
 */

// App logo URLs (using public CDN icons)
const APP_LOGOS = {
    "YouTube TV": "https://upload.wikimedia.org/wikipedia/commons/f/f7/YouTube_TV_logo.svg",
    "YouTube": "https://upload.wikimedia.org/wikipedia/commons/0/09/YouTube_full-color_icon_%282017%29.svg",
    "Netflix": "https://upload.wikimedia.org/wikipedia/commons/0/08/Netflix_2015_logo.svg",
    "Prime Video": "https://upload.wikimedia.org/wikipedia/commons/1/11/Amazon_Prime_Video_logo.svg",
    "Disney+": "https://upload.wikimedia.org/wikipedia/commons/3/3e/Disney%2B_logo.svg",
    "Hulu": "https://upload.wikimedia.org/wikipedia/commons/e/e4/Hulu_Logo.svg",
    "Max": "https://upload.wikimedia.org/wikipedia/commons/c/ce/Max_logo.svg",
    "Peacock": "https://upload.wikimedia.org/wikipedia/commons/d/d3/NBCUniversal_Peacock_Logo.svg",
    "Paramount+": "https://upload.wikimedia.org/wikipedia/commons/a/a5/Paramount_Plus.svg",
    "Apple TV+": "https://upload.wikimedia.org/wikipedia/commons/2/28/Apple_TV_Plus_Logo.svg",
    "Plex": "https://upload.wikimedia.org/wikipedia/commons/7/7b/Plex_logo_2022.svg",
};

class PosterDisplay {
    constructor() {
        // Elements
        this.header = document.getElementById("header");
        this.headerText = this.header.querySelector(".header-text");
        this.poster = document.getElementById("poster");
        this.posterInner = document.querySelector(".poster-inner");
        this.movieTitle = document.getElementById("movieTitle");
        this.movieYear = document.getElementById("movieYear");
        this.movieSynopsis = document.getElementById("movieSynopsis");
        this.playStatus = document.getElementById("playStatus");
        this.progressContainer = document.getElementById("progressContainer");
        this.progressFill = document.getElementById("progressFill");
        this.timeElapsed = document.getElementById("timeElapsed");
        this.timeRemaining = document.getElementById("timeRemaining");
        this.sourceIndicator = document.getElementById("sourceIndicator");
        this.debugIndicator = document.getElementById("debugIndicator");
        
        // State
        this.currentPosterUrl = "";
        this.currentMode = "";
        this.lastState = null;
        this.pollInterval = 2000; // 2 seconds
        
        // Start
        this.init();
    }
    
    init() {
        // Enable kiosk mode (hide cursor)
        document.body.classList.add("kiosk");
        
        // Start polling
        this.poll();
        setInterval(() => this.poll(), this.pollInterval);
        
        // Handle poster load events
        this.poster.addEventListener("load", () => {
            this.poster.classList.remove("loading");
            this.poster.classList.remove("fade-out");
            this.poster.classList.add("fade-in");
        });
        
        this.poster.addEventListener("error", () => {
            console.error("Failed to load poster:", this.poster.src);
            this.poster.classList.remove("loading");
        });
    }
    
    async poll() {
        try {
            const response = await fetch("/api/state");
            if (!response.ok) throw new Error("API error");
            
            const state = await response.json();
            this.updateDisplay(state);
        } catch (error) {
            console.error("Poll error:", error);
        }
    }
    
    getAppLogo(state) {
        // Try to find a logo for the current app
        if (state.synopsis) {
            for (const [appName, logoUrl] of Object.entries(APP_LOGOS)) {
                if (state.synopsis.includes(appName) || state.title === appName) {
                    return logoUrl;
                }
            }
        }
        return null;
    }
    
    updateDisplay(state) {
        const posterChanged = state.poster_url !== this.currentPosterUrl;
        
        // Update header based on mode
        this.headerText.classList.remove("coming-soon", "streaming", "idle");
        if (state.mode === "idle") {
            this.headerText.textContent = "POSTER DISPLAY";
            this.headerText.classList.add("idle");
        } else if (state.mode === "streaming") {
            this.headerText.textContent = "NOW STREAMING";
            this.headerText.classList.add("streaming");
        } else if (state.mode === "coming_soon") {
            this.headerText.textContent = "COMING SOON";
            this.headerText.classList.add("coming-soon");
        } else {
            this.headerText.textContent = "NOW SHOWING";
        }
        
        // Handle poster/image display
        this.poster.style.display = "";
        this.posterInner.classList.remove("streaming-mode", "app-logo-mode", "idle-mode");
        
        // Determine which image to show
        let imageUrl = state.poster_url;
        let isAppLogo = false;
        
        if (state.mode === "streaming" && !imageUrl) {
            // No TMDB poster, try app logo
            imageUrl = this.getAppLogo(state);
            isAppLogo = true;
        }
        
        if (imageUrl && imageUrl !== this.currentPosterUrl) {
            this.poster.classList.add("fade-out", "loading");
            // Check if this is a YouTube thumbnail (16:9 aspect ratio)
            const isYouTubeThumb = imageUrl.includes("ytimg.com") || imageUrl.includes("youtube.com");
            setTimeout(() => {
                this.poster.src = imageUrl;
                this.currentPosterUrl = imageUrl;
                // Remove previous mode classes
                this.poster.classList.remove("streaming-thumb");
                if (isAppLogo) {
                    this.posterInner.classList.add("app-logo-mode");
                } else if (isYouTubeThumb) {
                    // Use contain for YouTube thumbnails to avoid cropping
                    this.poster.classList.add("streaming-thumb");
                }
            }, 300);
        } else if (!imageUrl && state.mode === "streaming") {
            // No image at all, show placeholder
            this.posterInner.classList.add("streaming-mode");
            this.poster.style.display = "none";
            this.currentPosterUrl = "";
        } else if (state.mode === "idle") {
            // Idle/setup mode - show placeholder
            this.posterInner.classList.add("idle-mode");
            this.poster.style.display = "none";
            this.currentPosterUrl = "";
        }
        
        // Update title and year
        this.movieTitle.textContent = state.title || "";
        this.movieYear.textContent = state.year || "";
        
        // Update play status
        if (state.mode !== "coming_soon" && state.mode !== "idle" && state.mode !== "streaming") {
            const status = this.getStatusText(state);
            this.playStatus.textContent = status;
            this.playStatus.className = "play-status" + (state.play_status === "paused" ? " paused" : "");
        } else {
            this.playStatus.textContent = "";
        }
        
        // Update synopsis
        this.movieSynopsis.textContent = state.synopsis || "";
        
        // Update progress bar
        const showProgress = state.mode !== "coming_soon" && 
                            state.mode !== "idle" && 
                            state.mode !== "streaming" &&
                            state.duration_seconds > 0;
        
        if (showProgress) {
            this.progressContainer.classList.add("visible");
            this.progressFill.style.width = (state.progress_percent || 0) + "%";
            this.timeElapsed.textContent = this.formatTime(state.position_seconds);
            this.timeRemaining.textContent = this.formatTime(state.remaining_seconds) + " remaining";
        } else {
            this.progressContainer.classList.remove("visible");
        }
        
        // Update source indicator
        this.sourceIndicator.textContent = state.source_name || "";
        
        // Update debug indicator
        if (state.using_cached_input) {
            this.debugIndicator.textContent = "⚡ CACHED";
            this.debugIndicator.className = "debug-indicator cached";
        } else {
            this.debugIndicator.textContent = "● LIVE";
            this.debugIndicator.className = "debug-indicator live";
        }
        
        // Store last state
        this.lastState = state;
        this.currentMode = state.mode;
    }
    
    getStatusText(state) {
        if (!state.play_status || state.play_status === "none") return "";
        const statusMap = {
            "playing": "▶ Playing",
            "paused": "⏸ Paused",
            "forward": "⏩ Fast Forward",
            "reverse": "⏪ Rewind"
        };
        return statusMap[state.play_status] || state.play_status;
    }
    
    formatTime(seconds) {
        if (!seconds || seconds < 0) return "0:00";
        
        const hrs = Math.floor(seconds / 3600);
        const mins = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        
        if (hrs > 0) {
            return hrs + ":" + mins.toString().padStart(2, "0") + ":" + secs.toString().padStart(2, "0");
        }
        return mins + ":" + secs.toString().padStart(2, "0");
    }
}

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", () => {
    window.posterDisplay = new PosterDisplay();
});
