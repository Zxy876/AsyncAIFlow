package com.asyncaiflow.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class WebMvcConfig implements WebMvcConfigurer {

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        registry.addResourceHandler("/models/**")
                .addResourceLocations("file:/tmp/asyncaiflow-assembly-output/");

        registry.addResourceHandler("/scan-models/**")
                .addResourceLocations("file:/tmp/asyncaiflow-scan-output/");
    }
}
